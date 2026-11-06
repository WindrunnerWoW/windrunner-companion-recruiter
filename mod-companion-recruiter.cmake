if(NOT BUILD_PLAYERBOTS)
  message(FATAL_ERROR "mod-companion-recruiter requires BUILD_PLAYERBOTS=ON")
endif()

if(TORTOISE_CURRENT_MODULE_LINKAGE STREQUAL "dynamic")
  message(FATAL_ERROR
    "mod-companion-recruiter must be built statically because PlayerBots is a static, non-PIC library")
endif()

if(TORTOISE_MODULE_CMAKE_PHASE STREQUAL "POST_TARGETS")
  if(TORTOISE_CURRENT_MODULE_LINKAGE STREQUAL "dynamic")
    set(COMPANION_RECRUITER_TARGET mod_mod_companion_recruiter)
  else()
    set(COMPANION_RECRUITER_TARGET modules)
  endif()

  # PLAYERBOTS_IMPL is a cache variable of the AC playerbots port; the vanilla branches of this
  # repository never define it, so a stale -DPLAYERBOTS_IMPL=ac must not select the AC layout.
  # Key off the AC tree actually being present instead.
  if(PLAYERBOTS_IMPL STREQUAL "ac" AND EXISTS "${CMAKE_SOURCE_DIR}/src/modules/PlayerBotsAC/ac-compat/acpch.h")
    # The ported module exports its include directories through the playerbots target.
    target_compile_definitions(${COMPANION_RECRUITER_TARGET} PRIVATE MANGOSBOT_ZERO ENABLE_PLAYERBOTS PLAYERBOTS_AC)

    # playerbots exports only its AC header dirs; its core include dirs and the acpch.h precompiled
    # header stay PRIVATE. Scope both to the recruiter TU, because the modules target also builds
    # the other static modules, which must not see the force-included header.
    set_source_files_properties(
      ${CMAKE_SOURCE_DIR}/modules/mod-companion-recruiter/src/CompanionRecruiter.cpp
      PROPERTIES
        INCLUDE_DIRECTORIES
          "${CMAKE_SOURCE_DIR}/src/shared/Config;${CMAKE_SOURCE_DIR}/src/shared/Util;${CMAKE_SOURCE_DIR}/src/shared/Log;${CMAKE_SOURCE_DIR}/src/shared/Database;${BOOST_ROOT}"
        COMPILE_OPTIONS
          "/FI\"${CMAKE_SOURCE_DIR}/src/modules/PlayerBotsAC/ac-compat/acpch.h\"")
  else()
    target_include_directories(${COMPANION_RECRUITER_TARGET}
      PRIVATE
        ${CMAKE_SOURCE_DIR}/src/modules/PlayerBots
        ${CMAKE_SOURCE_DIR}/src/modules/PlayerBots/playerbot
        ${CMAKE_SOURCE_DIR}/src/modules/PlayerBots/playerbot/strategy)

    # The legacy bot tree's headers expect its own prelude: botpch.h pulls in the core headers first
    # and then cmangos-compat-shim.h, which supplies the typedefs they reach for (GenericTransport,
    # GuidSet, AreaTableEntry, TEAM_BOTH_ALLOWED). Scoped to the recruiter TU, because the modules
    # target also builds the other static modules, which must not see the force-included header.
    set_source_files_properties(
      ${CMAKE_SOURCE_DIR}/modules/mod-companion-recruiter/src/CompanionRecruiter.cpp
      PROPERTIES
        COMPILE_OPTIONS
          "/FI\"${CMAKE_SOURCE_DIR}/src/modules/PlayerBots/botpch.h\"")

    target_compile_definitions(${COMPANION_RECRUITER_TARGET} PRIVATE MANGOSBOT_ZERO ENABLE_PLAYERBOTS)
  endif()
  target_link_libraries(${COMPANION_RECRUITER_TARGET} PUBLIC playerbots)
endif()
