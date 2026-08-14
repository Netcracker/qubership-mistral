# -*- coding: robot -*-
# Resilience and disruption tests: HA, recovery jobs, queue recreation,
# headers propagation, notifications, K8s/DB/RabbitMQ management.

*** Variables ***
${ENGINE_DEPLOYMENT}       mistral-engine
${EXECUTOR_DEPLOYMENT}     mistral-executor
${NOTIFIER_DEPLOYMENT}     mistral-notifier
${API_DEPLOYMENT}          mistral-api
${MONITORING_DEPLOYMENT}   mistral-monitoring
${SCALE_WAIT_TIMEOUT}      180

${MISTRAL_CONFIGMAP}       custom-mistral.conf
${ENGINE_CONFIG_KEY}       custom-config-engine
${COMMON_CONFIG_KEY}       custom-config
${HA_TEST_TIMEOUT}         15 min
${KAFKA_NOTIFICATIONS_ENABLED}    %{KAFKA_NOTIFICATIONS_ENABLED=false}
${NOTIFICATION_WAIT}       120
${NOTIFICATION_STALE_BUFFER}    3


*** Settings ***
Resource  MistralKeywords.robot

Library  ../lib/KubernetesDisruptionLibrary.py
...                      namespace=%{KUBERNETES_NAMESPACE}
...                      rabbitmq_url=%{RABBITMQ_URL}
...                      rabbitmq_admin_user=%{RABBIT_ADMIN_USER}
...                      rabbitmq_admin_password=%{RABBIT_ADMIN_PASSWORD}
...                      rabbitmq_vhost=%{RABBIT_VHOST}
Force Tags       resilience
Suite Setup      Resilience Suite Setup
Test Setup       Wait Until Keyword Succeeds  3 min  5 sec  Set maintenance mode  RUNNING
Test Teardown    Wait Until Keyword Succeeds  3 min  5 sec  Common Test Teardown
Suite Teardown   Wait Until Keyword Succeeds  3 min  5 sec  Set maintenance mode  RUNNING


*** Keywords ***
Common Test Teardown
    Clear events
    Set maintenance mode  RUNNING
    Take off refuses

Restore All Deployments
    Scale Deployment  ${ENGINE_DEPLOYMENT}   replicas=1
    Scale Deployment  ${EXECUTOR_DEPLOYMENT}  replicas=1
    Scale Deployment  ${NOTIFIER_DEPLOYMENT}  replicas=1
    Scale Deployment  ${MONITORING_DEPLOYMENT}  replicas=1
    Wait Pods Ready  ${ENGINE_DEPLOYMENT}    expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Wait Pods Ready  ${EXECUTOR_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Wait Pods Ready  ${NOTIFIER_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Wait Pods Ready  ${MONITORING_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}

Get Guaranteed Notification Params
    [Documentation]  webhook_with_retries params matching guaranteed-notification cases.
    ${EVENTS}=  Create List  WORKFLOW_SUCCEEDED  WORKFLOW_FAILED  TASK_SUCCEEDED  TASK_FAILED
    ${EX_PARAMS}=  Get Event Params  ${EVENTS}  url=${OWN_URL}/wf_retry_notify
    ...    number_of_retries=10  polling_time=3
    RETURN  ${EX_PARAMS}

Simulate Subscriber Unavailable
    [Documentation]  Robot test pod webhook rejects requests.
    Set Fail Number  ${999}

Restore Subscriber
    Set Fail Number  ${0}

Guaranteed Notification Setup
    Skip If  not ${KAFKA_NOTIFICATIONS_ENABLED}  Kafka notifications not enabled
    Restore Subscriber

Assert Guaranteed Notifications Delivered
    [Documentation]  Wait for webhook notifications and assert state by task/workflow name.
    ...  Example: task1=ERROR  task2=SUCCESS  notification_delivery=SUCCESS
    [Arguments]  ${timeout}=${NOTIFICATION_WAIT}  &{expected}
    ${expected_count}=  Get Length  ${expected}
    &{received}=  Create Dictionary
    ${max_reads}=  Evaluate  ${expected_count} * ${NOTIFICATION_STALE_BUFFER}
    FOR  ${ignored}  IN RANGE  ${max_reads}
        ${received_count}=  Get Length  ${received}
        Exit For Loop If  ${received_count} == ${expected_count}
        ${notification}=  Await Rest  timeout=${timeout}
        ${name}=  Get From Dictionary  ${notification}  name
        Continue For Loop If  '${name}' not in $expected
        ${state}=  Get From Dictionary  ${notification}  state
        Set To Dictionary  ${received}  ${name}=${state}
    END
    Dictionaries Should Be Equal  ${received}  ${expected}

Notification Test Teardown
    Restore Subscriber
    Restore All Deployments
    Common Test Teardown

Restart All Mistral Deployments
    Restart Deployment  ${ENGINE_DEPLOYMENT}
    Restart Deployment  ${EXECUTOR_DEPLOYMENT}
    Restart Deployment  ${NOTIFIER_DEPLOYMENT}
    Restart Deployment  ${API_DEPLOYMENT}
    Restart Deployment  ${MONITORING_DEPLOYMENT}
    Wait Pods Ready  ${ENGINE_DEPLOYMENT}    expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Wait Pods Ready  ${EXECUTOR_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Wait Pods Ready  ${NOTIFIER_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Wait Pods Ready  ${API_DEPLOYMENT}       expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Wait Mistral Api
    Wait Mistral Engine And Executor
    Wait Pods Ready  ${MONITORING_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}

Set Custom Config Params And Restart
    [Documentation]  Upserts param lines under the given INI section in
    ...  custom-mistral.conf and restarts all Mistral pods to pick them up.
    ...  Saves the prior configmap value in ${ORIGINAL_CONFIG} for restore.
    [Arguments]  ${config_key}  ${section}  @{param_lines}
    ${current}=  Get Configmap Value  ${MISTRAL_CONFIGMAP}  ${config_key}
    Set Suite Variable  ${ORIGINAL_CONFIG}  ${current}
    Set Suite Variable  ${ORIGINAL_CONFIG_KEY}  ${config_key}
    ${new_config}=  Upsert Config Section  ${current}  ${section}  @{param_lines}
    Patch Configmap Value  ${MISTRAL_CONFIGMAP}  ${config_key}  ${new_config}
    Log To Console  patched ${MISTRAL_CONFIGMAP} section [${section}] with ${param_lines}
    Restart All Mistral Deployments

Assert Execution Has Propagated Headers
    [Documentation]  Creates an execution with extra headers and asserts
    ...  parent params.headers contains the expected keys. Used with
    ...  Wait Until Keyword Succeeds so API can finish loading custom config.
    [Arguments]  ${workflow_name}  ${ex_input}  ${extra_headers}  @{expected_headers}
    Create Execution With Headers  ${workflow_name}  ex_input=${ex_input}  extra_headers=${extra_headers}
    ${EX}=  Get execution
    ${params}=  Evaluate  json.loads($EX.params) if isinstance($EX.params, str) else dict($EX.params)  json
    Dictionary Should Contain Key  ${params}  headers
    ...  msg=Propagated headers are not captured into execution params (headers_propagation may still be disabled at runtime)
    ${captured}=  Set Variable  ${params['headers']}
    FOR  ${header_name}  IN  @{expected_headers}
        Dictionary Should Contain Key  ${captured}  ${header_name}
        ...  msg=Missing propagated header ${header_name} in params.headers=${captured}
    END
    RETURN  ${captured}

Restore Custom Config
    [Documentation]  Restores the configmap key captured by Set Custom Config Params And Restart
    ...  and restarts all Mistral pods.
    Patch Configmap Value  ${MISTRAL_CONFIGMAP}  ${ORIGINAL_CONFIG_KEY}  ${ORIGINAL_CONFIG}
    Restart All Mistral Deployments

Restore Config And Teardown
    Restore Custom Config
    Wait Until Keyword Succeeds  3 min  5 sec  Common Test Teardown

Restore Config And Deployments Teardown
    Restore All Deployments
    Restore Custom Config
    Wait Until Keyword Succeeds  3 min  5 sec  Common Test Teardown

Simulate Mistral Update Queue Recreation
    [Arguments]  ${queue_prefix}
    #Simulate Mistral update: scale down all services
    Scale Deployment  ${API_DEPLOYMENT}       replicas=0
    Scale Deployment  ${ENGINE_DEPLOYMENT}    replicas=0
    Scale Deployment  ${EXECUTOR_DEPLOYMENT}  replicas=0
    Scale Deployment  ${NOTIFIER_DEPLOYMENT}  replicas=0
    Wait Pods Ready  ${API_DEPLOYMENT}       expected_replicas=0  timeout=${SCALE_WAIT_TIMEOUT}
    Wait Pods Ready  ${ENGINE_DEPLOYMENT}    expected_replicas=0  timeout=${SCALE_WAIT_TIMEOUT}
    Wait Pods Ready  ${EXECUTOR_DEPLOYMENT}  expected_replicas=0  timeout=${SCALE_WAIT_TIMEOUT}
    Wait Pods Ready  ${NOTIFIER_DEPLOYMENT}  expected_replicas=0  timeout=${SCALE_WAIT_TIMEOUT}
    #Simulate Mistral update: delete mistral queues
    Delete Mistral Queues By Prefix  ${queue_prefix}
    #Simulate Mistral update: scale up all services
    Scale Deployment  ${API_DEPLOYMENT}       replicas=1
    Scale Deployment  ${ENGINE_DEPLOYMENT}    replicas=1
    Scale Deployment  ${EXECUTOR_DEPLOYMENT}  replicas=1
    Scale Deployment  ${NOTIFIER_DEPLOYMENT}  replicas=1
    Wait Pods Ready  ${API_DEPLOYMENT}       expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Wait Pods Ready  ${ENGINE_DEPLOYMENT}    expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Wait Pods Ready  ${EXECUTOR_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Wait Pods Ready  ${NOTIFIER_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}

Rerun Failed Task
    [Documentation]  Finds the first ERROR task in the current execution and reruns it.
    ${tasks}=  Get Tasks
    FOR  ${task}  IN  @{tasks}
        IF  '${task.state}' == 'ERROR'
            Rerun Task  ${task.name}
            RETURN
        END
    END
    Fail  No ERROR task found to rerun

Wait For Task Running State
    [Arguments]  ${timeout}=60
    ${start}=  Get Time  epoch
    WHILE    True
        ${ex}=  Get execution
        ${state}=  Set Variable  ${ex.state}
        IF  '${state}' == 'RUNNING'    BREAK
        ${elapsed}=  Evaluate  int(time.time()) - int(${start})  time
        IF  ${elapsed} > ${timeout}    Fail    Timeout waiting for RUNNING state
        Sleep  2s
    END

Resilience Suite Setup
    Wait Until Keyword Succeeds  3 min  5 sec  Delete stuck executions
    ${kafka_enabled_bool}=  Evaluate  '${KAFKA_NOTIFICATIONS_ENABLED}'.lower() == 'true'
    Set Suite Variable  ${KAFKA_NOTIFICATIONS_ENABLED}  ${kafka_enabled_bool}

Configure Short Recovery Timeouts
    [Documentation]  Short recovery_job timeouts + immediate integrity check.
    ${current}=  Get Configmap Value  ${MISTRAL_CONFIGMAP}  ${COMMON_CONFIG_KEY}
    Set Suite Variable  ${ORIGINAL_CONFIG}  ${current}
    Set Suite Variable  ${ORIGINAL_CONFIG_KEY}  ${COMMON_CONFIG_KEY}
    ${new_config}=  Upsert Config Section  ${current}  recovery_job
    ...    waiting_task_timeout = 10
    ...    expired_subwf_task_timeout = 10
    ...    stucked_subwf_task_timeout = 10
    ${new_config}=  Upsert Config Section  ${new_config}  engine
    ...    execution_integrity_check_delay = 0
    Patch Configmap Value  ${MISTRAL_CONFIGMAP}  ${COMMON_CONFIG_KEY}  ${new_config}
    Log To Console  patched ${MISTRAL_CONFIGMAP} section [recovery_job]/[engine] with short timeouts
    Restart All Mistral Deployments

Prepare Recovery Test Executions
    [Documentation]  Start 2 main_wf and 1 join workflow; store ids in suite variables.
    Recreate the recovery_subwf workbook
    ${ex}=  Create Execution  recovery_subwf.main_wf
    Set Suite Variable  ${RECOVERY_EXPIRED_ID}  ${ex}[id]
    Wait Until Keyword Succeeds  3 min  5 sec  Execution Has State  ${RECOVERY_EXPIRED_ID}  ERROR

    ${ex}=  Create Execution  recovery_subwf.main_wf
    Set Suite Variable  ${RECOVERY_STUCKED_ID}  ${ex}[id]
    Wait Until Keyword Succeeds  3 min  5 sec  Execution Has State  ${RECOVERY_STUCKED_ID}  ERROR

    Recreate the recovery_waiting_join workflow and start
    ${ex}=  Get execution
    Set Suite Variable  ${RECOVERY_WAITING_ID}  ${ex}[id]
    Wait Until Keyword Succeeds  3 min  5 sec  Execution Has State  ${RECOVERY_WAITING_ID}  ERROR

Corrupt Recovery Database States
    [Documentation]  psql updates for waiting / stucked / expired subwf cases.
    ${expired_task}=  Get Task  task2  ${RECOVERY_EXPIRED_ID}
    ${expired_child}=  Get Wf Ex By Task  task2  ${RECOVERY_EXPIRED_ID}
    ${stucked_task}=  Get Task  task2  ${RECOVERY_STUCKED_ID}
    ${waiting_task}=  Get Task  t2  ${RECOVERY_WAITING_ID}
    Corrupt All Recovery Case States
    ...    ${RECOVERY_EXPIRED_ID}  ${expired_child.id}  ${expired_task.id}
    ...    ${RECOVERY_STUCKED_ID}  ${stucked_task.id}
    ...    ${RECOVERY_WAITING_ID}  ${waiting_task.id}

Assert Recovery Jobs Healed Executions
    [Documentation]  After monitoring is back, all three executions should end in ERROR.
    Wait Until Keyword Succeeds  10 min  10 sec  All Recovery Executions Have ERROR
    ${expired}=  Get Execution  ${RECOVERY_EXPIRED_ID}
    Should Contain  ${expired.state_info}  no subwf for the long time

All Recovery Executions Have ERROR
    Execution Has State  ${RECOVERY_WAITING_ID}  ERROR
    Execution Has State  ${RECOVERY_STUCKED_ID}  ERROR
    Execution Has State  ${RECOVERY_EXPIRED_ID}  ERROR

*** Test Cases ***

Workflow output with non-limited execution field size
    [Tags]  boundaries
    [Timeout]  15 min
    [Teardown]  Restore Config And Teardown
    Set Custom Config Params And Restart  ${ENGINE_CONFIG_KEY}  engine  execution_field_size_limit_kb = -1

    ${OUTPUT_LENGTH}=  Set Variable  ${10240}
    ${EX_INPUT}=  Create Dictionary  output_length=${OUTPUT_LENGTH}
    Recreate the wf_size_limit_test workflow and start with ${EX_INPUT}
    wait until execution has state  SUCCESS  attempt=${60}  wait=${5}

    ${EX}=  Get execution
    ${output}=  Evaluate  json.loads($EX.output)  json
    Length Should Be  ${output['result']}  ${OUTPUT_LENGTH}



Headers propagation in sub-workflow
    [Tags]  headers
    [Timeout]  10 min
    [Teardown]  Restore Config And Teardown
    Set Custom Config Params And Restart  ${COMMON_CONFIG_KEY}  headers_propagation  enabled = true  template = Header.*
    ${PROPAGATED_HEADER}=    Set Variable    Header1
    ${PROPAGATED_HEADER_2}=    Set Variable    Header333
    ${EX_INPUT}=  Create Dictionary  headers_url=${OWN_URL}/headers

    Recreate the sub_wf_headers workflow
    Recreate the main_wf_headers workflow
    ${HEADERS}=  Create Dictionary  Header1=application/json  Header333=sobvbovba
    ${EXPECTED_HEADERS}=  Create List  ${PROPAGATED_HEADER}  ${PROPAGATED_HEADER_2}
    ${captured}=  Wait Until Keyword Succeeds  3 min  10 sec
    ...  Assert Execution Has Propagated Headers
    ...  main_wf_headers  ${EX_INPUT}  ${HEADERS}  @{EXPECTED_HEADERS}
    wait until execution has state  SUCCESS  attempt=${30}  wait=${5}

    ${SUB_EX}=  Get Wf Ex By Task  main_task
    ${sub_params}=  Evaluate  json.loads($SUB_EX.params) if isinstance($SUB_EX.params, str) else dict($SUB_EX.params)  json
    Dictionary Should Contain Key  ${sub_params}  headers
    ...  msg=Sub-workflow did not inherit params.headers from parent

    ${TASK}=  Get task  sub_http_task  ${SUB_EX.id}
    ${published}=  Evaluate  json.loads(str($TASK.published))  json
    ${received}=  Set Variable  ${published['received_headers']}
    Should Be Equal As Strings  ${received}[${PROPAGATED_HEADER}]  application/json
    Should Be Equal As Strings  ${received}[${PROPAGATED_HEADER_2}]  sobvbovba

Start workflow with incorrect input from task
    [Tags]  validation
    [Timeout]  5 min
    [Teardown]  Restore Config And Teardown
    Set Custom Config Params And Restart  ${ENGINE_CONFIG_KEY}  engine  start_subworkflows_via_rpc = true
    ${INPUT}=  Create Dictionary  a=a  b=b
    Recreate the incorrect_input_task workflow and start with ${INPUT}
    wait until execution has state  ERROR  attempt=${30}  wait=${5}

    ${EX}=  Get execution
    Should Contain  ${EX.state_info}  Invalid input


Parallel publish context is correctly merged
    [Tags]  context
    [Timeout]  5 min
    [Teardown]  Restore Config And Teardown
    Set Custom Config Params And Restart  ${ENGINE_CONFIG_KEY}  engine  merge_strategy = merge
    Recreate the parallel_publish_merge workflow
    create execution  parallel_publish_merge
    wait until execution has state  SUCCESS  attempt=${30}  wait=${5}

    ${EX}=  Get execution
    ${output}=  Evaluate  json.loads($EX.output)  json
    Should Be True  ${output} == {'A': 2, 'B': 2, 'C': 3, 'D': 2, 'E': 2, 'F': 2}

Guaranteed notification delivery - subscriber unavailable
    [Documentation]  subscriber down during execution, then recovered.
    [Tags]  notifications  kafka-notifications
    [Timeout]  15 min
    [Setup]  Skip If  not ${KAFKA_NOTIFICATIONS_ENABLED}  Kafka notifications not enabled

    ${EX_PARAMS}=  Get Guaranteed Notification Params
    Simulate Subscriber Unavailable
    Recreate the notification_delivery workflow and start params ${EX_PARAMS}
    wait until execution has state  SUCCESS  attempt=${30}  wait=${5}

    Clear events
    Restore Subscriber
    Assert Guaranteed Notifications Delivered
    ...    task1=ERROR  task2=SUCCESS  notification_delivery=SUCCESS


Guaranteed notification delivery - notifier unavailable
    [Documentation]  notifier scaled down, execution completes, notifications after scale up.
    [Tags]  notifications  kafka-notifications
    [Timeout]  15 min
    [Setup]  Guaranteed Notification Setup
    [Teardown]  Notification Test Teardown

    ${EX_PARAMS}=  Get Guaranteed Notification Params
    Scale Deployment  ${NOTIFIER_DEPLOYMENT}  replicas=0
    Wait Pods Ready  ${NOTIFIER_DEPLOYMENT}  expected_replicas=0  timeout=${SCALE_WAIT_TIMEOUT}

    Recreate the notification_delivery workflow and start params ${EX_PARAMS}
    wait until execution has state  SUCCESS  attempt=${30}  wait=${5}

    Scale Deployment  ${NOTIFIER_DEPLOYMENT}  replicas=1
    Wait Pods Ready  ${NOTIFIER_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Assert Guaranteed Notifications Delivered
    ...    task1=ERROR  task2=SUCCESS  notification_delivery=SUCCESS


Guaranteed notification delivery - engine unavailable mid-execution
    [Documentation]  parent2-like workflow, engine down during sleep, then recovered.
    [Tags]  notifications  kafka-notifications
    [Timeout]  15 min
    [Setup]  Guaranteed Notification Setup
    [Teardown]  Notification Test Teardown

    ${EX_PARAMS}=  Get Guaranteed Notification Params
    Recreate the notification_engine_restart workflow and start params ${EX_PARAMS}
    wait until execution has state  RUNNING  attempt=${20}  wait=${5}

    Scale Deployment  ${ENGINE_DEPLOYMENT}  replicas=0
    Wait Pods Ready  ${ENGINE_DEPLOYMENT}  expected_replicas=0  timeout=${SCALE_WAIT_TIMEOUT}
    Scale Deployment  ${ENGINE_DEPLOYMENT}  replicas=1
    Wait Pods Ready  ${ENGINE_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}

    wait until execution has state  SUCCESS  attempt=${90}  wait=${10}
    Assert Guaranteed Notifications Delivered
    ...    task1=SUCCESS  task2=SUCCESS  notification_engine_restart=SUCCESS


Guaranteed notification delivery - subscriber and notifier unavailable
    [Documentation]  subscriber down, then notifier down, recover notifier then subscriber.
    [Tags]  notifications  kafka-notifications
    [Timeout]  20 min
    [Setup]  Skip If  not ${KAFKA_NOTIFICATIONS_ENABLED}  Kafka notifications not enabled
    [Teardown]  Notification Test Teardown

    Clear events
    ${EX_PARAMS}=  Get Guaranteed Notification Params
    Simulate Subscriber Unavailable
    Recreate the notification_delivery workflow and start params ${EX_PARAMS}
    wait until execution has state  SUCCESS  attempt=${30}  wait=${5}

    Scale Deployment  ${NOTIFIER_DEPLOYMENT}  replicas=0
    Wait Pods Ready  ${NOTIFIER_DEPLOYMENT}  expected_replicas=0  timeout=${SCALE_WAIT_TIMEOUT}
    Sleep  60s

    Scale Deployment  ${NOTIFIER_DEPLOYMENT}  replicas=1
    Wait Pods Ready  ${NOTIFIER_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Clear events
    Restore Subscriber
    Assert Guaranteed Notifications Delivered
    ...    task1=ERROR  task2=SUCCESS  notification_delivery=SUCCESS


Mistral YAQL function doesn't change input
    [Tags]  context
    [Timeout]  5 min
    [Teardown]  Restore Config And Teardown
    Set Custom Config Params And Restart  ${ENGINE_CONFIG_KEY}  engine  merge_strategy = merge
    ${BLABLA_DICT}=  Create Dictionary  test_key=test_value
    ${EX_INPUT}=     Create Dictionary  blabla=${BLABLA_DICT}

    Recreate the yaql_immutable_input workflow and start with ${EX_INPUT}
    wait until execution has state  SUCCESS  attempt=${30}  wait=${5}

    ${EX}=  Get execution
    ${input}=   Evaluate  json.loads('''${EX.input}''')  modules=json
    ${output}=  Evaluate  json.loads('''${EX.output}''')  modules=json
    Should Be Equal  ${input}  ${EX_INPUT}
    ${EXPECTED_OUTPUT}=  Create Dictionary  blabla_input=${BLABLA_DICT}  blabla_output=${{ {"test_key": "test_value", "another_key": "another_value"} }}
    Should Be Equal  ${output}  ${EXPECTED_OUTPUT}


Recovery jobs heal stucked waiting and subworkflow tasks
    [Tags]  recovery
    [Timeout]  20 min
    [Teardown]  Restore Config And Deployments Teardown

    Configure Short Recovery Timeouts
    Prepare Recovery Test Executions
    Scale Deployment  ${MONITORING_DEPLOYMENT}  replicas=0
    Wait Pods Ready  ${MONITORING_DEPLOYMENT}  expected_replicas=0  timeout=${SCALE_WAIT_TIMEOUT}
    Corrupt Recovery Database States
    Scale Deployment  ${MONITORING_DEPLOYMENT}  replicas=1
    Wait Pods Ready  ${MONITORING_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Assert Recovery Jobs Healed Executions

Queues recreated on update with original arguments
    [Tags]  queues
    [Timeout]  15 min
    [Teardown]  Restore All Deployments

    ${EXECUTOR_QUEUE_PREFIX}=  Set Variable  mistral_mistral_executor
    ${CUSTOM_ARGS}=  Create Dictionary  test=custom

    Scale Deployment  ${EXECUTOR_DEPLOYMENT}  replicas=0
    Wait Pods Ready  ${EXECUTOR_DEPLOYMENT}  expected_replicas=0  timeout=${SCALE_WAIT_TIMEOUT}

    # Engine run_action casts without server → routing_key = shared topic name
    ${SHARED_QUEUE}=  Get Shared Executor Queue Name  ${EXECUTOR_QUEUE_PREFIX}
    #Log To Console  Using shared executor topic queue: ${SHARED_QUEUE}

    ${CLASSIC_CUSTOM_ARGS}=  Create Dictionary  x-queue-type=classic  x-ha-policy=all  test=custom
    Replace Queue With Custom Args  ${SHARED_QUEUE}  ${CLASSIC_CUSTOM_ARGS}  durable=${False}  prefix=${EXECUTOR_QUEUE_PREFIX}

    Scale Deployment  ${EXECUTOR_DEPLOYMENT}  replicas=1
    Wait Pods Ready  ${EXECUTOR_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Run Keyword And Ignore Error  Wait Executor Consumers  ${EXECUTOR_QUEUE_PREFIX}  timeout=60
    ${args_after_up}=  Get Queue Arguments  ${SHARED_QUEUE}
    Dictionary Should Contain Key  ${args_after_up}  test
    Should Be Equal As Strings  ${args_after_up}[test]  custom

    Scale Deployment  ${EXECUTOR_DEPLOYMENT}  replicas=0
    Wait Pods Ready  ${EXECUTOR_DEPLOYMENT}  expected_replicas=0  timeout=${SCALE_WAIT_TIMEOUT}
    Recreate the sleep_action workflow and start
    wait until execution has state  RUNNING  attempt=${20}  wait=${2}
    ${unread_count}=  Wait Until Keyword Succeeds  90s  5s
    ...    Work Queue Has Unread Messages  ${EXECUTOR_QUEUE_PREFIX}
    Log To Console  Custom queue '${EXECUTOR_QUEUE_PREFIX}' has unread=${unread_count}

    # Simulate mistral update → operator deletes queues + reconciles
    Simulate Mistral Update Queue Recreation  ${EXECUTOR_QUEUE_PREFIX}

    Wait Executor Consumers  ${EXECUTOR_QUEUE_PREFIX}  timeout=${SCALE_WAIT_TIMEOUT}
    ${SHARED_AFTER}=  Get Shared Executor Queue Name  ${EXECUTOR_QUEUE_PREFIX}
    Verify Queue Has No Custom Arguments  ${SHARED_AFTER}  ${CUSTOM_ARGS}
    ${msg_count_after}=  Get Work Queue Message Count  ${EXECUTOR_QUEUE_PREFIX}
    Should Be Equal As Integers  ${msg_count_after}  0
    ...    msg=Expected no messages after queue recreation but found ${msg_count_after}
    Log To Console  Updated queue '${EXECUTOR_QUEUE_PREFIX}' unread=${msg_count_after} (expected 0)


HA - Scaled down all pods when task in Running state
    [Tags]  ha
    [Timeout]  ${HA_TEST_TIMEOUT}
    [Teardown]  Restore Config And Deployments Teardown
    Set Custom Config Params And Restart  ${COMMON_CONFIG_KEY}  action_heartbeat
    ...    first_heartbeat_timeout = 2
    ...    check_interval = 5
    ...    max_missed_heartbeats = 2

    Recreate the ha_scale_down workflow and start
    wait until execution has state  RUNNING  wait=${10}

    Scale Deployment  ${ENGINE_DEPLOYMENT}   replicas=0
    Scale Deployment  ${EXECUTOR_DEPLOYMENT}  replicas=0
    Sleep  10s

    Scale Deployment  ${ENGINE_DEPLOYMENT}   replicas=1
    Scale Deployment  ${EXECUTOR_DEPLOYMENT}  replicas=1
    Wait Pods Ready  ${ENGINE_DEPLOYMENT}   expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Wait Pods Ready  ${EXECUTOR_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}

    wait until execution has state  ERROR  attempt=${90}  wait=${10}
    Rerun Failed Task
    wait until execution has state  SUCCESS  attempt=${90}  wait=${10}


HA - Tasks retry after executor is down
    [Tags]  ha
    [Timeout]  ${HA_TEST_TIMEOUT}
    [Teardown]  Restore Config And Deployments Teardown
    Set Custom Config Params And Restart  ${COMMON_CONFIG_KEY}  action_heartbeat
    ...    first_heartbeat_timeout = 2
    ...    check_interval = 5
    ...    max_missed_heartbeats = 2

    Recreate the ha_retry_workflow workflow and start
    Wait For Task Running State  timeout=60
    Scale Deployment  ${EXECUTOR_DEPLOYMENT}  replicas=0
    wait until execution has state  ERROR  attempt=${90}  wait=${10}

    ${EX}=  Get execution
    Should Contain  ${EX.state_info}  Heartbeat wasn't received

    number of actions equals  retry_task  21

    Scale Deployment  ${EXECUTOR_DEPLOYMENT}  replicas=1
    Wait Pods Ready  ${EXECUTOR_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Rerun Failed Task
    wait until execution has state  ERROR  attempt=${90}  wait=${10}

HA - Workflow succeeds after engine and executor pods are force killed
    [Tags]  ha
    [Timeout]  ${HA_TEST_TIMEOUT}
    [Teardown]  Common Test Teardown

    Recreate the ha_pod_kill_workflow workflow and start
    wait until execution has state  RUNNING  attempt=${20}  wait=${5}

    Delete Pods For Deployment  ${ENGINE_DEPLOYMENT}   grace_period=0
    Delete Pods For Deployment  ${EXECUTOR_DEPLOYMENT}  grace_period=0

    Wait Pods Ready  ${ENGINE_DEPLOYMENT}   expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    Wait Pods Ready  ${EXECUTOR_DEPLOYMENT}  expected_replicas=1  timeout=${SCALE_WAIT_TIMEOUT}
    wait until execution has state  SUCCESS  attempt=${90}  wait=${10}
