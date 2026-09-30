# vendor 维度：每个变体只编译一个 vendor 的词表、loader 与后端。
# 默认变体是 agora，保持既有构建与测试入口不变。
set(BEACON_MAC_COMMON_SOURCES
  src/platform/agent_provider_registry.cc
  src/platform/network_condition_provider.cc
  src/platform/permission_manager.cc
  src/platform/platform_log_bridge.cc
  src/platform/platform_adapter.cc
  src/rtc/rtc_event_bridge.cc
  src/rtc/rtc_invocation_provider.cc
  src/video/view_registry.cc
  src/video/video_host_provider.cc
)

add_library(beacon_mac_mock STATIC
  ${BEACON_MAC_COMMON_SOURCES}
  src/platform/permission_manager_mock.cc
  src/vendors/agora/agora_visual_probe_provider.cc
  src/vendors/agora/agora_sdk_loader.cc
  src/vendors/agora/rtc_backend_mock.cc
  src/vendors/agora/rtc_invocation_provider_agora.cc
)

target_include_directories(beacon_mac_mock PUBLIC src)
target_link_libraries(beacon_mac_mock PUBLIC beacon_agent_core)

add_library(beacon_mac_mock_volcengine STATIC
  ${BEACON_MAC_COMMON_SOURCES}
  src/platform/permission_manager_mock.cc
  src/vendors/volcengine/volcengine_sdk_loader.cc
  src/vendors/volcengine/volcengine_visual_probe_provider.cc
  src/vendors/volcengine/rtc_backend_mock_volcengine.cc
  src/vendors/volcengine/rtc_invocation_provider_volcengine.cc
)

target_include_directories(beacon_mac_mock_volcengine PUBLIC src)
# vendor 是变体属性：链接该库的目标（测试/示例）必须用同一套词表。
target_compile_definitions(beacon_mac_mock_volcengine PUBLIC BEACON_MAC_RTC_VENDOR_VOLCENGINE=1)
target_link_libraries(beacon_mac_mock_volcengine PUBLIC beacon_agent_core)

option(BEACON_ENABLE_AGORA_REAL "Build the macOS Agora real RTC backend when the SDK is available" OFF)
set(BEACON_AGORA_FRAMEWORK "")
set(BEACON_AGORA_DYLD_FRAMEWORK_PATH "")
if(APPLE AND DEFINED ENV{AGORA_MAC_SDK_ROOT})
  set(BEACON_AGORA_ROOT "$ENV{AGORA_MAC_SDK_ROOT}")
  # 官方完整包把 AgoraRtcKit 与 aosl 放在 libs/；优先解析该目录，确保运行时依赖也在
  # DYLD_FRAMEWORK_PATH 内，而不是只找到孤立的 AgoraRtcKit.xcframework。
  if(EXISTS "${BEACON_AGORA_ROOT}/Shengwang_Native_SDK_for_Mac_FULL/libs/AgoraRtcKit.xcframework")
    set(BEACON_AGORA_ROOT "${BEACON_AGORA_ROOT}/Shengwang_Native_SDK_for_Mac_FULL/libs")
  endif()
  if(EXISTS "${BEACON_AGORA_ROOT}/AgoraRtcKit.framework")
    set(BEACON_AGORA_FRAMEWORK "${BEACON_AGORA_ROOT}/AgoraRtcKit.framework")
    set(BEACON_AGORA_DYLD_FRAMEWORK_PATH "${BEACON_AGORA_ROOT}")
  else()
    file(GLOB BEACON_AGORA_XCFRAMEWORK_CANDIDATES
      "${BEACON_AGORA_ROOT}/AgoraRtcKit.xcframework/macos-*/AgoraRtcKit.framework"
      "${BEACON_AGORA_ROOT}/AgoraRtcKit.xcframework/*-macos*/AgoraRtcKit.framework"
    )
    file(GLOB BEACON_AGORA_FRAMEWORK_SLICE_DIRS
      "${BEACON_AGORA_ROOT}/*.xcframework/macos-*"
      "${BEACON_AGORA_ROOT}/*.xcframework/*-macos*"
    )
    list(JOIN BEACON_AGORA_FRAMEWORK_SLICE_DIRS ":" BEACON_AGORA_DYLD_FRAMEWORK_PATH)
    list(LENGTH BEACON_AGORA_XCFRAMEWORK_CANDIDATES BEACON_AGORA_XCFRAMEWORK_COUNT)
    if(BEACON_AGORA_XCFRAMEWORK_COUNT GREATER 0)
      list(GET BEACON_AGORA_XCFRAMEWORK_CANDIDATES 0 BEACON_AGORA_FRAMEWORK)
    endif()
  endif()
  if(BEACON_AGORA_FRAMEWORK)
    set(BEACON_ENABLE_AGORA_REAL ON CACHE BOOL "Build the macOS Agora real RTC backend when the SDK is available" FORCE)
  endif()
endif()

add_executable(mac_mock_adapter_test tests/mac_mock_adapter_test.cc)
target_link_libraries(mac_mock_adapter_test PRIVATE beacon_mac_mock)
if(APPLE)
  target_sources(mac_mock_adapter_test PRIVATE
    tests/video_host_activation_test.mm
    demo/mac_real_agent_packet_handler.mm
    demo/mac_real_agent_loopback_helper.mm
  )
  target_include_directories(mac_mock_adapter_test PRIVATE demo)
  target_compile_options(mac_mock_adapter_test PRIVATE -fobjc-arc)
  target_link_libraries(mac_mock_adapter_test PRIVATE "-framework Foundation" "-framework AppKit")
endif()

if(APPLE)
  add_test(NAME BRIDGE-MAC-VIDEO-HOST-ACTIVATION COMMAND mac_mock_adapter_test BRIDGE-MAC-VIDEO-HOST-ACTIVATION)
endif()

add_executable(mac_mock_demo demo/mac_mock_demo.cc)
target_link_libraries(mac_mock_demo PRIVATE beacon_mac_mock)

add_executable(mac_mock_volcengine_test tests/mac_mock_volcengine_test.cc)
target_link_libraries(mac_mock_volcengine_test PRIVATE beacon_mac_mock_volcengine)
target_include_directories(mac_mock_volcengine_test PRIVATE tests)

if(APPLE AND BEACON_ENABLE_AGORA_REAL AND BEACON_AGORA_FRAMEWORK)
  add_library(beacon_mac_real STATIC
    ${BEACON_MAC_COMMON_SOURCES}
    src/platform/permission_manager_real.mm
    src/vendors/agora/agora_visual_probe_provider.cc
    src/vendors/agora/agora_sdk_loader.cc
    src/vendors/agora/rtc_backend_real.mm
    src/vendors/agora/rtc_invocation_provider_agora.cc
    src/video/synthetic_video_clip.mm
  )
  target_include_directories(beacon_mac_real PUBLIC src)
  target_compile_options(beacon_mac_real PRIVATE -fobjc-arc)
  target_compile_definitions(beacon_mac_real PRIVATE BEACON_MAC_REAL_BACKEND=1)
  target_link_libraries(beacon_mac_real PUBLIC beacon_agent_core "-framework Foundation" "-framework AppKit"
    "-framework AVFoundation" "-framework CoreGraphics" "-framework CoreMedia" "-framework CoreVideo" "${BEACON_AGORA_FRAMEWORK}")

  add_executable(mac_real_adapter_test tests/mac_real_adapter_test.mm)
  target_link_libraries(mac_real_adapter_test PRIVATE beacon_mac_real)

  add_test(NAME BRIDGE-MAC-REAL-01 COMMAND mac_real_adapter_test BRIDGE-MAC-REAL-01)
  add_test(NAME BRIDGE-MAC-REAL-02 COMMAND mac_real_adapter_test BRIDGE-MAC-REAL-02)
  add_test(NAME IT-AGORA-04 COMMAND mac_real_adapter_test IT-AGORA-04)
  add_test(NAME IT-AGORA-MULTI-REMOTE-BINDINGS COMMAND mac_real_adapter_test IT-AGORA-MULTI-REMOTE-BINDINGS)
  add_test(NAME IT-AGORA-VISUAL-PROBE COMMAND mac_real_adapter_test IT-AGORA-VISUAL-PROBE)
  add_test(NAME IT-AGORA-JOIN-CALLBACK COMMAND mac_real_adapter_test IT-AGORA-JOIN-CALLBACK)
  add_test(NAME IT-AGORA-LEAVE-CHANNEL COMMAND mac_real_adapter_test IT-AGORA-LEAVE-CHANNEL)
  add_test(NAME IT-AGORA-STOP-PREVIEW COMMAND mac_real_adapter_test IT-AGORA-STOP-PREVIEW)
  add_test(NAME IT-AGORA-SYNTHETIC-VIDEO COMMAND mac_real_adapter_test IT-AGORA-SYNTHETIC-VIDEO)
  add_test(NAME IT-AGORA-MEDIA-PLAYER COMMAND mac_real_adapter_test IT-AGORA-MEDIA-PLAYER)
  add_test(NAME IT-AGORA-PERMISSION-DENIED COMMAND mac_real_adapter_test IT-AGORA-PERMISSION-DENIED)
  add_test(NAME IT-AGORA-PROTOCOL-COMMANDS COMMAND mac_real_adapter_test IT-AGORA-PROTOCOL-COMMANDS)
  add_test(NAME FI-RTC-01 COMMAND mac_real_adapter_test FI-RTC-01)

  set_tests_properties(
    BRIDGE-MAC-REAL-01
    BRIDGE-MAC-REAL-02
    IT-AGORA-04
    IT-AGORA-VISUAL-PROBE
    IT-AGORA-MULTI-REMOTE-BINDINGS
    IT-AGORA-JOIN-CALLBACK
    IT-AGORA-LEAVE-CHANNEL
    IT-AGORA-STOP-PREVIEW
    IT-AGORA-SYNTHETIC-VIDEO
    IT-AGORA-MEDIA-PLAYER
    IT-AGORA-PERMISSION-DENIED
    IT-AGORA-PROTOCOL-COMMANDS
    FI-RTC-01
    PROPERTIES
      WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
      ENVIRONMENT "DYLD_FRAMEWORK_PATH=${BEACON_AGORA_DYLD_FRAMEWORK_PATH}"
  )
else()
  message(STATUS "Agora macOS real backend disabled; set AGORA_MAC_SDK_ROOT to a SDK root containing AgoraRtcKit.framework or AgoraRtcKit.xcframework")
endif()

# 火山真实变体：SDK 是多 framework + dylib 组合，全部依赖都是 @rpath 相对路径，
# 因此链接时显式给出 -rpath 指向 SDK 根（dylib 与 framework 同目录）。
option(BEACON_ENABLE_VOLCENGINE_REAL "Build the macOS Volcengine real RTC backend when the SDK is available" OFF)
# 根路径每次 configure 从环境变量重算；变体的启用条件同时要求根非空，
# 否则上一次配置缓存的 ON 会在 SDK 环境缺失时留下「变体开着但根为空」的坏状态。
set(BEACON_VOLCENGINE_ROOT "")
if(APPLE AND DEFINED ENV{VOLCENGINE_MAC_SDK_ROOT})
  set(BEACON_VOLCENGINE_ROOT "$ENV{VOLCENGINE_MAC_SDK_ROOT}")
  if(EXISTS "${BEACON_VOLCENGINE_ROOT}/VolcEngineRTC.framework")
    set(BEACON_ENABLE_VOLCENGINE_REAL ON CACHE BOOL "Build the macOS Volcengine real RTC backend when the SDK is available" FORCE)
  endif()
endif()

if(APPLE AND BEACON_ENABLE_VOLCENGINE_REAL AND BEACON_VOLCENGINE_ROOT)
  set(BEACON_VOLCENGINE_LINK_ITEMS
    "${BEACON_VOLCENGINE_ROOT}/VolcEngineRTC.framework"
    "${BEACON_VOLCENGINE_ROOT}/RTCFFmpeg.framework"
    "${BEACON_VOLCENGINE_ROOT}/ByteRTCFFmpegAudioExtension.framework"
    "${BEACON_VOLCENGINE_ROOT}/ByteRTCFDK-AACExtension.framework"
    "${BEACON_VOLCENGINE_ROOT}/ByteRTCNICOExtension.framework"
    "${BEACON_VOLCENGINE_ROOT}/ByteRTCVp8CodecExtension.framework"
    "${BEACON_VOLCENGINE_ROOT}/libbytevc0.dylib"
    "${BEACON_VOLCENGINE_ROOT}/libbytenn.dylib"
    "${BEACON_VOLCENGINE_ROOT}/libbdaudioeffect.dylib"
    "${BEACON_VOLCENGINE_ROOT}/libeffect.dylib"
  )

  add_library(beacon_mac_real_volcengine STATIC
    ${BEACON_MAC_COMMON_SOURCES}
    src/platform/permission_manager_real.mm
    src/vendors/volcengine/volcengine_sdk_loader.cc
    src/vendors/volcengine/volcengine_visual_probe_provider.cc
    src/vendors/volcengine/rtc_backend_real_volcengine.mm
    src/vendors/volcengine/rtc_invocation_provider_volcengine.cc
    src/video/synthetic_video_clip.mm
  )
  target_include_directories(beacon_mac_real_volcengine PUBLIC src)
  # framework 式 import（<VolcEngineRTC/...>）需要编译期 -F；CMake 只为链接加了它。
  target_compile_options(beacon_mac_real_volcengine PRIVATE "-F${BEACON_VOLCENGINE_ROOT}")
  # 必须开 ARC：MRR 下传给 SDK 的 NSString（roomId 等）会随 autoreleasepool 提前释放，
  # SDK 在后续 leave 的同步 barrier 里再读它们就成了悬垂指针（真实 gate 间歇性段错误）。
  target_compile_options(beacon_mac_real_volcengine PRIVATE -fobjc-arc)
  target_compile_definitions(beacon_mac_real_volcengine PUBLIC BEACON_MAC_RTC_VENDOR_VOLCENGINE=1)
  target_compile_definitions(beacon_mac_real_volcengine PRIVATE BEACON_MAC_REAL_BACKEND=1)
  target_link_libraries(beacon_mac_real_volcengine PUBLIC beacon_agent_core
    "-framework Foundation" "-framework AppKit" "-framework AVFoundation" "-framework CoreGraphics" "-framework CoreMedia" "-framework CoreVideo"
    ${BEACON_VOLCENGINE_LINK_ITEMS})
  target_link_options(beacon_mac_real_volcengine PUBLIC "-Wl,-rpath,${BEACON_VOLCENGINE_ROOT}")

  add_executable(mac_real_volcengine_adapter_test tests/mac_real_volcengine_adapter_test.mm)
  target_link_libraries(mac_real_volcengine_adapter_test PRIVATE beacon_mac_real_volcengine)

  # 火山真实变体的原生 Agent 进程：同一套 demo 传输/协议处理，链到火山真实库。
  add_executable(mac_volcengine_agent_bridge
    demo/mac_real_agent_bridge.mm
    demo/mac_real_agent_transport.mm
    demo/mac_real_agent_packet_handler.mm
    demo/mac_real_agent_loopback_helper.mm
  )
  target_compile_options(mac_volcengine_agent_bridge PRIVATE -fobjc-arc)
  target_link_libraries(mac_volcengine_agent_bridge PRIVATE beacon_mac_real_volcengine "-framework Foundation" "-framework AppKit")

  add_test(NAME BUILD-MAC-VOLCENGINE-REAL-01 COMMAND mac_real_volcengine_adapter_test BUILD-MAC-VOLCENGINE-REAL-01)
  add_test(NAME IT-VOLCENGINE-REAL-MULTI-REMOTE-BINDINGS COMMAND mac_real_volcengine_adapter_test IT-VOLCENGINE-REAL-MULTI-REMOTE-BINDINGS)
  add_test(NAME IT-VOLCENGINE-REAL-01 COMMAND mac_real_volcengine_adapter_test IT-VOLCENGINE-REAL-01)
  add_test(NAME IT-VOLCENGINE-REAL-02 COMMAND mac_real_volcengine_adapter_test IT-VOLCENGINE-REAL-02)
  add_test(NAME IT-VOLCENGINE-REAL-JOIN-LEAVE COMMAND mac_real_volcengine_adapter_test IT-VOLCENGINE-REAL-JOIN-LEAVE)
  set_tests_properties(
    BUILD-MAC-VOLCENGINE-REAL-01
    IT-VOLCENGINE-REAL-01
    IT-VOLCENGINE-REAL-MULTI-REMOTE-BINDINGS
    IT-VOLCENGINE-REAL-02
    IT-VOLCENGINE-REAL-JOIN-LEAVE
    PROPERTIES WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
  )
elseif(APPLE)
  message(STATUS "Volcengine macOS real backend disabled; set VOLCENGINE_MAC_SDK_ROOT to a SDK root containing VolcEngineRTC.framework")
endif()

option(BEACON_ENABLE_ZEGO_REAL "Build the macOS ZEGO real RTC backend when the SDK is available" OFF)
set(BEACON_ZEGO_FRAMEWORK "")
set(BEACON_ZEGO_FRAMEWORK_SLICE "")
if(APPLE AND DEFINED ENV{ZEGO_MAC_SDK_ROOT})
  set(BEACON_ZEGO_ROOT "$ENV{ZEGO_MAC_SDK_ROOT}")
  if(EXISTS "${BEACON_ZEGO_ROOT}/ZegoExpressEngine.framework")
    set(BEACON_ZEGO_FRAMEWORK "${BEACON_ZEGO_ROOT}/ZegoExpressEngine.framework")
    set(BEACON_ZEGO_FRAMEWORK_SLICE "${BEACON_ZEGO_ROOT}")
  else()
    file(GLOB BEACON_ZEGO_XCFRAMEWORK_CANDIDATES
      "${BEACON_ZEGO_ROOT}/ZegoExpressEngine.xcframework/macos-*/ZegoExpressEngine.framework"
    )
    list(LENGTH BEACON_ZEGO_XCFRAMEWORK_CANDIDATES BEACON_ZEGO_XCFRAMEWORK_COUNT)
    if(BEACON_ZEGO_XCFRAMEWORK_COUNT GREATER 0)
      list(GET BEACON_ZEGO_XCFRAMEWORK_CANDIDATES 0 BEACON_ZEGO_FRAMEWORK)
      get_filename_component(BEACON_ZEGO_FRAMEWORK_SLICE "${BEACON_ZEGO_FRAMEWORK}" DIRECTORY)
    endif()
  endif()
  if(BEACON_ZEGO_FRAMEWORK)
    set(BEACON_ENABLE_ZEGO_REAL ON CACHE BOOL "Build the macOS ZEGO real RTC backend when the SDK is available" FORCE)
  endif()
endif()

if(APPLE AND BEACON_ENABLE_ZEGO_REAL AND BEACON_ZEGO_FRAMEWORK)
  add_library(beacon_mac_real_zego STATIC
    ${BEACON_MAC_COMMON_SOURCES}
    src/platform/permission_manager_real.mm
    src/vendors/zego/zego_sdk_loader.cc
    src/vendors/zego/zego_visual_probe_provider.cc
    src/vendors/zego/rtc_backend_real_zego.mm
    src/vendors/zego/rtc_invocation_provider_zego.cc
    src/video/synthetic_video_clip.mm
  )
  target_include_directories(beacon_mac_real_zego PUBLIC src)
  target_compile_options(beacon_mac_real_zego PRIVATE "-F${BEACON_ZEGO_FRAMEWORK_SLICE}" -fobjc-arc)
  target_compile_definitions(beacon_mac_real_zego PUBLIC BEACON_MAC_RTC_VENDOR_ZEGO=1)
  target_compile_definitions(beacon_mac_real_zego PRIVATE BEACON_MAC_REAL_BACKEND=1)
  target_link_libraries(beacon_mac_real_zego PUBLIC beacon_agent_core
    "-framework Foundation" "-framework AppKit" "-framework AVFoundation" "-framework CoreGraphics" "-framework CoreMedia" "-framework CoreVideo" "${BEACON_ZEGO_FRAMEWORK}")
  target_link_options(beacon_mac_real_zego PUBLIC "-Wl,-rpath,${BEACON_ZEGO_FRAMEWORK_SLICE}")

  add_executable(mac_zego_agent_bridge
    demo/mac_real_agent_bridge.mm
    demo/mac_real_agent_transport.mm
    demo/mac_real_agent_packet_handler.mm
    demo/mac_real_agent_loopback_helper.mm
  )
  target_compile_options(mac_zego_agent_bridge PRIVATE -fobjc-arc)
  target_link_libraries(mac_zego_agent_bridge PRIVATE beacon_mac_real_zego "-framework Foundation" "-framework AppKit")
else()
  message(STATUS "ZEGO macOS real backend disabled; set ZEGO_MAC_SDK_ROOT to a SDK root containing ZegoExpressEngine.framework or ZegoExpressEngine.xcframework")
endif()

if(APPLE)
  add_executable(mac_real_agent_bridge
    demo/mac_real_agent_bridge.mm
    demo/mac_real_agent_transport.mm
    demo/mac_real_agent_packet_handler.mm
    demo/mac_real_agent_loopback_helper.mm
  )
  target_compile_options(mac_real_agent_bridge PRIVATE -fobjc-arc)
  if(BEACON_ENABLE_AGORA_REAL AND BEACON_AGORA_FRAMEWORK)
    target_link_libraries(mac_real_agent_bridge PRIVATE beacon_mac_real)
  else()
    target_link_libraries(mac_real_agent_bridge PRIVATE beacon_mac_mock "-framework Foundation" "-framework AppKit")
  endif()
endif()

add_test(NAME BUILD-MAC-DEMO COMMAND mac_mock_demo)
add_test(NAME BUILD-MAC-01 COMMAND mac_mock_adapter_test BUILD-MAC-01)
add_test(NAME BRIDGE-MAC-01 COMMAND mac_mock_adapter_test BRIDGE-MAC-01)
add_test(NAME BRIDGE-MAC-02 COMMAND mac_mock_adapter_test BRIDGE-MAC-02)
add_test(NAME BRIDGE-MAC-03 COMMAND mac_mock_adapter_test BRIDGE-MAC-03)
add_test(NAME BRIDGE-MAC-04 COMMAND mac_mock_adapter_test BRIDGE-MAC-04)
add_test(NAME BRIDGE-MAC-06 COMMAND mac_mock_adapter_test BRIDGE-MAC-06)
add_test(NAME BRIDGE-MAC-EVENT COMMAND mac_mock_adapter_test BRIDGE-MAC-EVENT)
add_test(NAME BRIDGE-MAC-LIFECYCLE COMMAND mac_mock_adapter_test BRIDGE-MAC-LIFECYCLE)
add_test(NAME BRIDGE-MAC-PROVIDER COMMAND mac_mock_adapter_test BRIDGE-MAC-PROVIDER)
add_test(NAME BRIDGE-MAC-PROVIDER-ROUTE COMMAND mac_mock_adapter_test BRIDGE-MAC-PROVIDER-ROUTE)
add_test(NAME BRIDGE-MAC-TARGET-CONSISTENCY COMMAND mac_mock_adapter_test BRIDGE-MAC-TARGET-CONSISTENCY)
add_test(NAME BRIDGE-MAC-VIDEO-HOST COMMAND mac_mock_adapter_test BRIDGE-MAC-VIDEO-HOST)
add_test(NAME BRIDGE-MAC-VIDEO-HOST-LAYOUT COMMAND mac_mock_adapter_test BRIDGE-MAC-VIDEO-HOST-LAYOUT)
add_test(NAME BRIDGE-MAC-VIDEO-STATS-OVERLAY COMMAND mac_mock_adapter_test BRIDGE-MAC-VIDEO-STATS-OVERLAY)
add_test(NAME BRIDGE-MAC-SIMULCAST COMMAND mac_mock_adapter_test BRIDGE-MAC-SIMULCAST)
add_test(NAME BRIDGE-MAC-BACKEND-WIRING COMMAND mac_mock_adapter_test BRIDGE-MAC-BACKEND-WIRING)
add_test(NAME BRIDGE-MAC-BACKEND-FAILURES COMMAND mac_mock_adapter_test BRIDGE-MAC-BACKEND-FAILURES)
add_test(NAME BRIDGE-MAC-PROVIDER-FAILURES COMMAND mac_mock_adapter_test BRIDGE-MAC-PROVIDER-FAILURES)
add_test(NAME BRIDGE-MAC-JOIN-CALLBACK-TIMEOUT-FIXTURE COMMAND mac_mock_adapter_test BRIDGE-MAC-JOIN-CALLBACK-TIMEOUT-FIXTURE)
add_test(NAME BRIDGE-MAC-PERMISSION-FIXTURE COMMAND mac_mock_adapter_test BRIDGE-MAC-PERMISSION-FIXTURE)
add_test(NAME BRIDGE-MAC-RENEW-TOKEN COMMAND mac_mock_adapter_test BRIDGE-MAC-RENEW-TOKEN)
add_test(NAME BRIDGE-MAC-LOCAL-MEDIA-ENABLE COMMAND mac_mock_adapter_test BRIDGE-MAC-LOCAL-MEDIA-ENABLE)
add_test(NAME BRIDGE-MAC-SYNTHETIC-VIDEO COMMAND mac_mock_adapter_test BRIDGE-MAC-SYNTHETIC-VIDEO)
add_test(NAME BRIDGE-MAC-VISUAL-PROBE COMMAND mac_mock_adapter_test BRIDGE-MAC-VISUAL-PROBE)
add_test(NAME BRIDGE-MAC-VOCABULARY COMMAND mac_mock_adapter_test BRIDGE-MAC-VOCABULARY)
add_test(NAME BRIDGE-MAC-PLATFORM-LOG COMMAND mac_mock_adapter_test BRIDGE-MAC-PLATFORM-LOG)
add_test(NAME BRIDGE-MAC-REDACTION COMMAND mac_mock_adapter_test BRIDGE-MAC-REDACTION)
add_test(NAME FI-NETWORK-CONDITION-01 COMMAND mac_mock_adapter_test FI-NETWORK-CONDITION-01)
add_test(NAME FI-NETWORK-CONDITION-02 COMMAND mac_mock_adapter_test FI-NETWORK-CONDITION-02)
add_test(NAME FI-NETWORK-CONDITION-03 COMMAND mac_mock_adapter_test FI-NETWORK-CONDITION-03)
add_test(NAME FI-NETWORK-CONDITION-04 COMMAND mac_mock_adapter_test FI-NETWORK-CONDITION-04)
add_test(NAME FI-NETWORK-CONDITION-05 COMMAND mac_mock_adapter_test FI-NETWORK-CONDITION-05)

# 火山变体：携带 SDK 名的测试入口，只校验 volcengine_rtc 的契约行。
add_test(NAME BUILD-MAC-VOLCENGINE-01 COMMAND mac_mock_volcengine_test BUILD-MAC-VOLCENGINE-01)
add_test(NAME BUILD-MAC-VOLCENGINE-02 COMMAND mac_mock_volcengine_test BUILD-MAC-VOLCENGINE-02)
add_test(NAME BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE COMMAND mac_mock_volcengine_test BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE)
add_test(NAME BRIDGE-MAC-VOLCENGINE-PROVIDER-FAILURES COMMAND mac_mock_volcengine_test BRIDGE-MAC-VOLCENGINE-PROVIDER-FAILURES)
add_test(NAME BRIDGE-MAC-VOLCENGINE-VOCABULARY COMMAND mac_mock_volcengine_test BRIDGE-MAC-VOLCENGINE-VOCABULARY)
add_test(NAME BRIDGE-MAC-VOLCENGINE-JOIN-LEAVE COMMAND mac_mock_volcengine_test BRIDGE-MAC-VOLCENGINE-JOIN-LEAVE)
add_test(NAME BRIDGE-MAC-VOLCENGINE-UNDECLARED-STATE COMMAND mac_mock_volcengine_test BRIDGE-MAC-VOLCENGINE-UNDECLARED-STATE)
add_test(NAME BRIDGE-MAC-VOLCENGINE-JOIN-PARAMS COMMAND mac_mock_volcengine_test BRIDGE-MAC-VOLCENGINE-JOIN-PARAMS)
add_test(NAME BRIDGE-MAC-VOLCENGINE-VISUAL-PROBE COMMAND mac_mock_volcengine_test BRIDGE-MAC-VOLCENGINE-VISUAL-PROBE)
add_test(NAME BRIDGE-MAC-VOLCENGINE-VIDEO-OPS COMMAND mac_mock_volcengine_test BRIDGE-MAC-VOLCENGINE-VIDEO-OPS)
add_test(NAME BRIDGE-MAC-VOLCENGINE-TARGET-CONSISTENCY COMMAND mac_mock_volcengine_test BRIDGE-MAC-VOLCENGINE-TARGET-CONSISTENCY)

set_tests_properties(
  BUILD-MAC-01
  BUILD-MAC-DEMO
  BRIDGE-MAC-01
  BRIDGE-MAC-02
  BRIDGE-MAC-03
  BRIDGE-MAC-04
  BRIDGE-MAC-06
  BRIDGE-MAC-VIDEO-STATS-OVERLAY
  BRIDGE-MAC-SIMULCAST
  BRIDGE-MAC-EVENT
  BRIDGE-MAC-LIFECYCLE
  BRIDGE-MAC-PROVIDER
  BRIDGE-MAC-PROVIDER-ROUTE
  BRIDGE-MAC-TARGET-CONSISTENCY
  BRIDGE-MAC-BACKEND-WIRING
  BRIDGE-MAC-BACKEND-FAILURES
  BRIDGE-MAC-PROVIDER-FAILURES
  BRIDGE-MAC-JOIN-CALLBACK-TIMEOUT-FIXTURE
  BRIDGE-MAC-PERMISSION-FIXTURE
  BRIDGE-MAC-RENEW-TOKEN
  BRIDGE-MAC-LOCAL-MEDIA-ENABLE
  BRIDGE-MAC-SYNTHETIC-VIDEO
  BRIDGE-MAC-VISUAL-PROBE
  BRIDGE-MAC-VOCABULARY
  BRIDGE-MAC-PLATFORM-LOG
  BRIDGE-MAC-REDACTION
  FI-NETWORK-CONDITION-01
  FI-NETWORK-CONDITION-02
  FI-NETWORK-CONDITION-03
  FI-NETWORK-CONDITION-04
  FI-NETWORK-CONDITION-05
  BUILD-MAC-VOLCENGINE-01
  BUILD-MAC-VOLCENGINE-02
  BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE
  BRIDGE-MAC-VOLCENGINE-PROVIDER-FAILURES
  BRIDGE-MAC-VOLCENGINE-VOCABULARY
  BRIDGE-MAC-VOLCENGINE-JOIN-LEAVE
  BRIDGE-MAC-VOLCENGINE-UNDECLARED-STATE
  BRIDGE-MAC-VOLCENGINE-JOIN-PARAMS
  BRIDGE-MAC-VOLCENGINE-VISUAL-PROBE
  BRIDGE-MAC-VOLCENGINE-VIDEO-OPS
  BRIDGE-MAC-VOLCENGINE-TARGET-CONSISTENCY
  PROPERTIES WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)

add_executable(mac_permission_test
  tests/permission_manager_test.cc
  src/platform/permission_manager.cc
  src/platform/permission_manager_mock.cc
)
target_include_directories(mac_permission_test PRIVATE src)
add_dependencies(mac_mock_adapter_test mac_permission_test)
add_test(NAME BRIDGE-MAC-PERMISSION-STATUS COMMAND mac_permission_test)

if(APPLE)
  # 原生权限映射与异步接缝不依赖 SDK；测试只用注入状态，不申请系统权限。
  add_executable(mac_permission_native_test
    tests/permission_manager_native_test.mm
    src/platform/permission_manager.cc
    src/platform/permission_manager_real.mm
  )
  target_include_directories(mac_permission_native_test PRIVATE src)
  add_dependencies(mac_mock_adapter_test mac_permission_native_test)
  target_compile_options(mac_permission_native_test PRIVATE -fobjc-arc)
  target_link_libraries(mac_permission_native_test PRIVATE "-framework Foundation" "-framework AVFoundation" "-framework CoreGraphics")
  add_test(NAME BRIDGE-MAC-PERMISSION-NATIVE COMMAND mac_permission_native_test)
endif()
