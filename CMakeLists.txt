cmake_minimum_required(VERSION 3.16)
if(APPLE)
  project(Beacon LANGUAGES CXX OBJCXX)
else()
  project(Beacon LANGUAGES CXX)
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

enable_testing()
add_subdirectory(agent_core)
add_subdirectory(agents/mac)
