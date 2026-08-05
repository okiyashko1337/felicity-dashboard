#pragma once

#include <stddef.h>

#include "setup_input.h"
#include "device_settings.h"
#include "wifi_manager.h"

typedef enum {
    LOCAL_SETUP_ACTION_NONE = 0,
    LOCAL_SETUP_ACTION_BACK,
    LOCAL_SETUP_ACTION_WIFI,
    LOCAL_SETUP_ACTION_HA,
    LOCAL_SETUP_ACTION_RETRY,
    LOCAL_SETUP_ACTION_DOWN,
    LOCAL_SETUP_ACTION_UP,
    LOCAL_SETUP_ACTION_TIME_MINUS,
    LOCAL_SETUP_ACTION_TIME_PLUS,
    LOCAL_SETUP_ACTION_TIME_DST,
    LOCAL_SETUP_ACTION_NAV_NETWORK,
    LOCAL_SETUP_ACTION_NAV_TIME,
    LOCAL_SETUP_ACTION_NAV_RESET,
    LOCAL_SETUP_ACTION_RESET,
    LOCAL_SETUP_ACTION_RESET_CANCEL,
    LOCAL_SETUP_ACTION_RESET_CONFIRM,
} local_setup_action_t;

void setup_ui_render_scanning(void);
void setup_ui_render_networks(size_t page, const char *message);
void setup_ui_render_keyboard(const char *ssid, const char *password,
                              bool symbols, bool uppercase, bool show_password,
                              const char *message);
void setup_ui_render_password(const char *password, bool show_password,
                              const char *message);
void setup_ui_render_api_keyboard(const char *url, bool symbols,
                                  bool uppercase, const char *message);
void setup_ui_render_connecting(const char *ssid);
void setup_ui_render_connection_log(
    const char *ssid,
    const char lines[][FELICITY_WIFI_LOG_LINE_MAX], size_t line_count,
    bool failed, bool connected);
void setup_ui_connection_log_touch_feedback(uint16_t x, uint16_t y,
                                            bool pressed);
void setup_ui_network_touch_feedback(uint16_t x, uint16_t y, size_t page,
                                     size_t network_count, bool pressed);
void setup_ui_keyboard_touch_feedback(uint16_t x, uint16_t y, bool symbols,
                                      bool uppercase, bool pressed);
void setup_ui_render_local_settings(const wifi_diagnostics_t *wifi,
                                    const char *ha_host, bool ha_live,
                                    const char *status, unsigned page,
                                    const device_time_settings_t *time_settings,
                                    const char *ha_app_version,
                                    const char *monitor_version,
                                    uint32_t uptime_seconds);
local_setup_action_t setup_ui_local_settings_hit(uint16_t x, uint16_t y,
                                                  unsigned page);
void setup_ui_local_settings_touch_feedback(uint16_t x, uint16_t y,
                                            bool pressed, unsigned page);
void setup_ui_render_time_value(void);
void setup_ui_render_wizard_exit_top(bool visible);
void setup_ui_render_wizard_exit_bottom(bool visible);
void setup_ui_wizard_exit_touch_feedback(bool bottom, bool pressed);
void setup_ui_render_factory_reset_result(bool success);
void setup_ui_render_wizard_exit_status(void);
