# CMakeLists.txt —— winmm.dll 劫持框架（实验性 / 高风险）
# ⚠️ 免责声明见同目录 README.md。本工程仅供技术研究，严禁作弊用途。
cmake_minimum_required(VERSION 3.20)
project(ETSHookWinmm LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ---- 查找 Detours ----
# 通过 vcpkg 或 DETOURS_ROOT 指定
if(DEFINED ENV{DETOURS_ROOT})
    set(DETOURS_ROOT $ENV{DETOURS_ROOT})
endif()
find_path(DETOURS_INCLUDE_DIRS "detours/detours.h"
    PATHS ${DETOURS_ROOT}/include ${DETOURS_ROOT}/src)
find_library(DETOURS_LIBRARY detours
    PATHS ${DETOURS_ROOT}/lib ${DETOURS_ROOT}/lib.X64 ${DETOURS_ROOT}/lib.x64)

if(NOT DETOURS_LIBRARY)
    message(FATAL_ERROR "未找到 Detours 库，请设置 DETOURS_ROOT 或通过 vcpkg 安装 detours")
endif()

# ---- 导出转发 ----
# 导出转发已通过 winmm_hook.cpp 中的 #pragma comment(linker,"/EXPORT:...")
# 指向同目录的 winmm_orig.dll（构建脚本会从 System32 拷贝并重命名）。
# 不再依赖 .def 文件，避免与 pragma 冲突。

add_library(ETSHookWinmm SHARED winmm_hook.cpp)
target_include_directories(ETSHookWinmm PRIVATE ${DETOURS_INCLUDE_DIRS})
target_link_libraries(ETSHookWinmm PRIVATE ${DETOURS_LIBRARY})

# 输出文件名为 winmm.dll（无 lib 前缀），用于 DLL 搜索顺序劫持
set_target_properties(ETSHookWinmm PROPERTIES
    OUTPUT_NAME "winmm"
    PREFIX "")

# ---- 构建后：把系统 winmm.dll 拷贝为 winmm_orig.dll 到输出目录 ----
# 转发目标 winmm_orig.<fn> 必须存在于同目录，否则程序加载会失败。
add_custom_command(TARGET ETSHookWinmm POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "$ENV{WINDIR}/System32/winmm.dll"
        "$<TARGET_FILE_DIR:ETSHookWinmm>/winmm_orig.dll"
    COMMENT "拷贝 System32\\winmm.dll -> winmm_orig.dll（转发目标）")
