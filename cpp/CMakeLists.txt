# CMakeLists.txt —— 给 MSVC / Visual Studio 用的构建入口。
# MinGW 用户请直接用 build.bat（不需要装 CMake）。
# MSVC 用法：cmake -S cpp -B cpp/build-msvc -G "Visual Studio 17 2022" -A x64 && cmake --build cpp/build-msvc --config Release
cmake_minimum_required(VERSION 3.16)
project(ScreenWatermark LANGUAGES CXX RC)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

set(SRC
  src/main.cpp
  src/config.cpp
  src/overlay.cpp
  src/tray.cpp
  src/settings.cpp
  src/util.cpp
  src/hotkey.cpp
  res/app.rc
)

add_executable(ScreenWatermark WIN32 ${SRC})

# Unicode 入口（wWinMain）+ Unicode API，全工程统一宽字符
target_compile_definitions(ScreenWatermark PRIVATE UNICODE _UNICODE)

# 源码是 UTF-8（含中文注释和字面量），MSVC 必须显式指定，否则中文全变问号
if(MSVC)
  target_compile_options(ScreenWatermark PRIVATE /utf-8 /W4 /permissive-)
  # 我们自己带了 manifest（res/app.rc），关掉 CMake 默认插的那份，两份会打架
  set_target_properties(ScreenWatermark PROPERTIES LINK_FLAGS "/MANIFEST:NO")
else()
  target_compile_options(ScreenWatermark PRIVATE -Wall -Wextra
                         -finput-charset=UTF-8 -fexec-charset=UTF-8)
  # 静态链接 GCC 运行库，拷到没装 MinGW 的机器上也能跑
  target_link_options(ScreenWatermark PRIVATE -static-libgcc -static-libstdc++)
endif()

# gdiplus 是唯一的外部依赖，其余都是系统库
target_link_libraries(ScreenWatermark PRIVATE
  gdiplus user32 gdi32 shell32 advapi32 ole32 comctl32 comdlg32 iphlpapi)

# 配置/资源都相对 exe，输出统一放 build 目录
set_target_properties(ScreenWatermark PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
  RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_BINARY_DIR}"
  RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}")
