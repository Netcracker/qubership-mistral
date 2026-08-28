# -*- coding: robot -*-
# Shared variables, libraries, and keywords for Mistral test suites.
# Import this file as a Resource in Mistral.robot and Mistral_resilience.robot.

*** Variables ***
${OWN_URL}                 %{OWN_URL}
${AUTH_ENABLE}             %{AUTH_ENABLE}
${TENANT}                  system
${WORKFLOW_NAMESPACE}      tests
${KUBERNETES_NAMESPACE}    %{KUBERNETES_NAMESPACE}
${MISTRAL_SERVICE_NAME}    %{MISTRAL_HOST}
${MISTRAL_CR_NAME}         mistral-service
${MISTRAL_SECRET_NAME}     mistral-secret
${DBAAS_USER}              %{DBAAS_USER=}
${DBAAS_PASSWORD}          %{DBAAS_PASSWORD=}


*** Settings ***
Library  BuiltIn
Library  OperatingSystem
Library  ../lib/Mistral.py  mistral_url=%{MISTRAL_URL}
...                      auth_enable=%{AUTH_ENABLE}
...                      auth_type=%{AUTH_TYPE}
...                      client_register_token=%{CLIENT_REGISTRATION_TOKEN}
...                      idp_server=%{IDP_SERVER}
...                      tenant=${TENANT}
...                      idp_user=%{IDP_USER}
...                      idp_password=%{IDP_PASSWORD}
...                      idp_client_id=%{IDP_CLIENT_ID}
...                      idp_client_secret=%{IDP_CLIENT_SECRET}
...                      workflow_namespace=${WORKFLOW_NAMESPACE}
Library  ../lib/HttpServerLibrary.py  mistral_url=%{MISTRAL_URL}
Library  ../lib/UtilsLibrary.py
Library  PlatformLibrary  managed_by_operator=true
Library  RequestsLibrary
Library  String
Library  Collections


*** Keywords ***
DBaaS Integration Is Enabled
    ${cr}=    Get Custom Resource    netcracker.com/v2    mistralservice
    ...    ${KUBERNETES_NAMESPACE}    ${MISTRAL_CR_NAME}
    ${enabled}=    Set Variable    ${cr['spec']['mistralCommonParams']['dbaas']['integrationEnabled']}
    RETURN    ${enabled}

Get DBaaS Connection Properties
    ${cr}=    Get Custom Resource    netcracker.com/v2    mistralservice
    ...    ${KUBERNETES_NAMESPACE}    ${MISTRAL_CR_NAME}
    ${aggregator_url}=    Set Variable    ${cr['spec']['mistralCommonParams']['dbaas']['aggregatorUrl']}
    ${auth}=    Create List    ${DBAAS_USER}    ${DBAAS_PASSWORD}
    ${session}=    Create Session    dbaas    ${aggregator_url}
    ...    auth=${auth}
    ${classifier}=    Create Dictionary
    ...    microserviceName=mistral-operator    scope=service    namespace=${KUBERNETES_NAMESPACE}
    ${body}=    Create Dictionary    classifier=${classifier}    originService=mistral-operator
    ${resp}=    POST On Session    dbaas
    ...    /api/v3/dbaas/${KUBERNETES_NAMESPACE}/databases/get-by-classifier/postgresql
    ...    json=${body}
    Should Be Equal As Integers    ${resp.status_code}    200
    ...    msg=DBaaS get-by-classifier failed: ${resp.text}
    RETURN    ${resp.json()['connectionProperties']}

Recreate the ${name} workflow
    delete workflow     ${name}
    create workflow     ${name}

Recreate the ${name} workflow and start
    delete workflow     ${name}
    create workflow     ${name}

    create execution    ${name}

Recreate the ${name} workflow and start with ${input}
    delete workflow     ${name}
    create workflow     ${name}

    ${EX}=  create execution    ${name}  ex_input=${input}
    RETURN  ${EX}

Recreate ${name} workflow and start with input from ${file_name}
    delete workflow     ${name}
    create workflow     ${name}

    ${EX}=  create_execution_with_file_input    ${name}  input_file_name=${file_name}
    RETURN  ${EX}

Recreate the ${name} workflow and start params ${params}
    delete workflow     ${name}
    create workflow     ${name}

    create execution    ${name}  params=${params}

Recreate the ${name} workflow, start and wait ${state} state
    delete workflow     ${name}
    create workflow     ${name}

    create execution    ${name}
    Wait until the execution will has ${state} state

Recreate the ${name} workflow, start with ${input} and wait ${state} state
    delete workflow     ${name}
    create workflow     ${name}

    create execution    ${name}  ex_input=${input}
    Wait until the execution will has ${state} state

Recreate the ${name} workflow and starts with ${input} and params ${params}
    delete workflow     ${name}
    create workflow     ${name}

    ${EX}=  create execution    ${name}  ex_input=${input}  params=${params}

Recreate the ${name} workbook
    delete workbook     ${name}
    create workbook     ${name}

Wait until the execution will has ${state} state
    wait until execution has state  ${state}

${param} of ${name} task must be equal ${value}
    task param equals   ${name}     ${param}=${value}

Compare Images From Resources With Dd
    [Arguments]  ${dd_images}
    ${stripped_resources}=  Strip String  ${dd_images}  characters=,  mode=right
    @{list_resources} =  Split String	${stripped_resources} 	,
    FOR  ${resource}  IN  @{list_resources}
      ${type}  ${name}  ${container_name}  ${image}=  Split String	${resource}
      ${resource_image}=  Get Resource Image  ${type}  ${name}  ${KUBERNETES_NAMESPACE}  ${container_name}
      Should Be Equal  ${resource_image}  ${image}
    END
