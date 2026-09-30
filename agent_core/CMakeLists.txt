include(FetchContent)

find_package(jsoncpp CONFIG QUIET)
if(NOT jsoncpp_FOUND)
  FetchContent_Declare(
    jsoncpp
    URL https://github.com/open-source-parsers/jsoncpp/archive/refs/tags/1.9.6.tar.gz
    URL_HASH SHA256=f93b6dd7ce796b13d02c108bc9f79812245a82e577581c4c9aabe57075c90ea2
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
  )
  set(JSONCPP_WITH_TESTS OFF CACHE BOOL "" FORCE)
  set(JSONCPP_WITH_POST_BUILD_UNITTEST OFF CACHE BOOL "" FORCE)
  set(JSONCPP_WITH_WARNING_AS_ERROR OFF CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(jsoncpp)
endif()

find_package(spdlog CONFIG QUIET)
if(NOT spdlog_FOUND)
  FetchContent_Declare(
    spdlog
    URL https://github.com/gabime/spdlog/archive/refs/tags/v1.15.3.tar.gz
    URL_HASH SHA256=15a04e69c222eb6c01094b5c7ff8a249b36bb22788d72519646fb85feb267e67
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
  )
  set(SPDLOG_BUILD_TESTS OFF CACHE BOOL "" FORCE)
  set(SPDLOG_BUILD_EXAMPLE OFF CACHE BOOL "" FORCE)
  set(SPDLOG_INSTALL OFF CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(spdlog)
endif()

add_library(beacon_agent_core STATIC
  src/callback_controller.cc
  src/invocation_controller.cc
  src/logging.cc
  src/platform_log_bridge.cc
  src/protocol_json.cc
  src/protocol_codec.cc
  src/protocol_validator.cc
  src/resource_vault.cc
  src/runner_kernel.cc
  src/target_contract.cc
  src/version.cc
)

target_include_directories(beacon_agent_core PUBLIC include)
target_link_libraries(beacon_agent_core PUBLIC jsoncpp_lib PRIVATE spdlog::spdlog)

add_executable(protocol_codec_test tests/protocol_codec_test.cc)
target_link_libraries(protocol_codec_test PRIVATE beacon_agent_core)
add_test(NAME UT-PC-01 COMMAND protocol_codec_test)

add_executable(protocol_validator_test tests/protocol_validator_test.cc)
target_link_libraries(protocol_validator_test PRIVATE beacon_agent_core)
add_test(NAME UT-PV-01 COMMAND protocol_validator_test)

add_executable(target_contract_test tests/target_contract_test.cc)
target_link_libraries(target_contract_test PRIVATE beacon_agent_core)
add_test(NAME UT-TC-01 COMMAND target_contract_test)

add_executable(invocation_controller_test tests/invocation_controller_test.cc)
target_link_libraries(invocation_controller_test PRIVATE beacon_agent_core)
add_test(NAME UT-INV-01 COMMAND invocation_controller_test)

add_executable(callback_controller_test tests/callback_controller_test.cc)
target_link_libraries(callback_controller_test PRIVATE beacon_agent_core)
add_test(NAME UT-CB-01 COMMAND callback_controller_test)

add_executable(resource_vault_test tests/resource_vault_test.cc)
target_link_libraries(resource_vault_test PRIVATE beacon_agent_core)
add_test(NAME UT-MODEL-01 COMMAND resource_vault_test)

add_executable(runner_kernel_test tests/runner_kernel_test.cc)
target_link_libraries(runner_kernel_test PRIVATE beacon_agent_core)
add_test(NAME UT-CBEVT-01 COMMAND runner_kernel_test)

add_executable(logging_test tests/logging_test.cc)
target_link_libraries(logging_test PRIVATE beacon_agent_core)
add_test(NAME UT-LOG-01 COMMAND logging_test)

set_tests_properties(
  UT-PC-01
  UT-PV-01
  UT-TC-01
  UT-INV-01
  UT-CB-01
  UT-MODEL-01
  UT-CBEVT-01
  UT-LOG-01
  PROPERTIES WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
