#include "wifi_setup.h"

#include <stdio.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_system.h"
#include "sdkconfig.h"

#include "nextion.h"
#include "device_settings.h"
#include "setup_ui.h"
#include "wifi_manager.h"
#include "wifi_portal.h"

typedef enum {
    SCREEN_SCANNING = 0,
    SCREEN_NETWORKS,
    SCREEN_KEYBOARD,
    SCREEN_CONNECTING,
} setup_screen_t;

static void append_character(char *value, size_t capacity, char character)
{
    size_t length = strlen(value);
    if (length + 1 < capacity) {
        value[length] = character;
        value[length + 1] = '\0';
    }
}

static void render_scanning(bool can_exit)
{
    setup_ui_render_scanning();
    setup_ui_render_wizard_exit_top(can_exit);
}

static void render_networks(size_t page, const char *message, bool can_exit)
{
    setup_ui_render_networks(page, message);
    setup_ui_render_wizard_exit_top(can_exit);
}

static void render_connection_log(
    const char *ssid,
    const char lines[][FELICITY_WIFI_LOG_LINE_MAX], size_t line_count,
    bool failed, bool connected, bool can_exit)
{
    setup_ui_render_connection_log(ssid, lines, line_count, failed, connected);
    setup_ui_render_wizard_exit_bottom(can_exit && !connected);
}

static void exit_to_saved_wifi(void)
{
    setup_ui_render_wizard_exit_status();
    vTaskDelay(pdMS_TO_TICKS(300));
    esp_restart();
}

void wifi_setup_run(char *api_url, size_t api_url_capacity)
{
    char saved_ssid[FELICITY_WIFI_SSID_MAX + 1] = "";
    char saved_password[FELICITY_WIFI_PASSWORD_MAX] = "";
    char fallback_ssid[FELICITY_WIFI_SSID_MAX + 1] = "";
    char fallback_password[FELICITY_WIFI_PASSWORD_MAX] = "";
    char selected_ssid[FELICITY_WIFI_SSID_MAX + 1] = "";
    char password[FELICITY_WIFI_PASSWORD_MAX] = "";
    char message[32] = "";
    size_t network_page = 0;
    bool symbols = false;
    bool uppercase = false;
    bool show_password = false;
    bool interactive_connection = false;
    bool connection_failed = false;
    uint32_t rendered_log_revision = 0;
    setup_screen_t screen;

    bool staged_credentials = wifi_manager_take_staged_credentials(
        saved_ssid, sizeof(saved_ssid), saved_password, sizeof(saved_password));
    bool force_interactive_setup = wifi_manager_take_setup_request();
    wifi_manager_init();
    wifi_portal_start();
    bool stored_credentials = wifi_manager_load_credentials(
        fallback_ssid, sizeof(fallback_ssid), fallback_password,
        sizeof(fallback_password));
    bool configured_credentials = CONFIG_FELICITY_WIFI_SSID[0] != '\0';
    bool can_exit = (force_interactive_setup || staged_credentials) &&
                    (stored_credentials || configured_credentials);
    bool have_credentials = staged_credentials;
    if (!have_credentials && stored_credentials) {
        snprintf(saved_ssid, sizeof(saved_ssid), "%s", fallback_ssid);
        snprintf(saved_password, sizeof(saved_password), "%s", fallback_password);
        have_credentials = true;
    }
    if (!have_credentials && CONFIG_FELICITY_WIFI_SSID[0]) {
        snprintf(saved_ssid, sizeof(saved_ssid), "%s", CONFIG_FELICITY_WIFI_SSID);
        snprintf(saved_password, sizeof(saved_password), "%s", CONFIG_FELICITY_WIFI_PASSWORD);
        have_credentials = true;
    }

    if (force_interactive_setup) have_credentials = false;
    if (have_credentials) {
        snprintf(selected_ssid, sizeof(selected_ssid), "%s", saved_ssid);
        snprintf(password, sizeof(password), "%s", saved_password);
        interactive_connection = staged_credentials;
        wifi_manager_connect(selected_ssid, password, true);
        char log_lines[FELICITY_WIFI_LOG_MAX_LINES][FELICITY_WIFI_LOG_LINE_MAX];
        size_t log_count = wifi_manager_log_snapshot(
            log_lines, FELICITY_WIFI_LOG_MAX_LINES, &rendered_log_revision);
        render_connection_log(selected_ssid, log_lines, log_count, false, false,
                              can_exit);
        screen = SCREEN_CONNECTING;
    } else {
        wifi_manager_start_scan();
        render_scanning(can_exit);
        screen = SCREEN_SCANNING;
    }
    memset(saved_password, 0, sizeof(saved_password));
    memset(fallback_password, 0, sizeof(fallback_password));

    while (wifi_manager_state() != WIFI_MANAGER_CONNECTED) {
        wifi_manager_tick();
        wifi_manager_state_t manager_state = wifi_manager_state();

        if (screen == SCREEN_CONNECTING) {
            char log_lines[FELICITY_WIFI_LOG_MAX_LINES][FELICITY_WIFI_LOG_LINE_MAX];
            uint32_t revision = 0;
            size_t log_count = wifi_manager_log_snapshot(
                log_lines, FELICITY_WIFI_LOG_MAX_LINES, &revision);
            bool failed = manager_state == WIFI_MANAGER_FAILED;
            if (revision != rendered_log_revision || failed != connection_failed) {
                connection_failed = failed;
                rendered_log_revision = revision;
                render_connection_log(selected_ssid, log_lines, log_count,
                                      failed, false, can_exit);
            }
        }

        if (manager_state == WIFI_MANAGER_SCAN_READY && screen == SCREEN_SCANNING) {
            size_t count = wifi_manager_network_count();
            size_t page_count = count ? (count + SETUP_WIFI_ROWS_PER_PAGE - 1) /
                                           SETUP_WIFI_ROWS_PER_PAGE
                                     : 1;
            if (network_page >= page_count) network_page = 0;
            render_networks(network_page, message, can_exit);
            screen = SCREEN_NETWORKS;
            message[0] = '\0';
        } else if (manager_state == WIFI_MANAGER_FAILED && screen == SCREEN_CONNECTING) {
            int reason = wifi_manager_last_disconnect_reason();
            snprintf(message, sizeof(message), "FAILED (%d)", reason);
        }

        touch_event_t touch;
        if (nextion_read_touch_event(&touch)) {
            uint16_t x = touch.x;
            uint16_t y = touch.y;
            bool exit_top = can_exit &&
                            (screen == SCREEN_SCANNING ||
                             screen == SCREEN_NETWORKS) &&
                            x >= 360 && y < 44;
            bool exit_bottom = can_exit && screen == SCREEN_CONNECTING &&
                               x >= 344 && y >= 224;
            if (exit_top || exit_bottom) {
                setup_ui_wizard_exit_touch_feedback(exit_bottom, touch.pressed);
            } else if (screen == SCREEN_NETWORKS) {
                setup_ui_network_touch_feedback(x, y, network_page,
                                                wifi_manager_network_count(),
                                                touch.pressed);
            } else if (screen == SCREEN_KEYBOARD) {
                setup_ui_keyboard_touch_feedback(x, y, symbols, uppercase,
                                                 touch.pressed);
            } else if (screen == SCREEN_CONNECTING && connection_failed) {
                setup_ui_connection_log_touch_feedback(x, y, touch.pressed);
            }
            if (touch.pressed) {
                vTaskDelay(pdMS_TO_TICKS(20));
                continue;
            }
            if (exit_top || exit_bottom) exit_to_saved_wifi();
            if (screen == SCREEN_CONNECTING && connection_failed &&
                x < 128 && y >= 224) {
                connection_failed = false;
                if (interactive_connection) {
                    setup_ui_render_keyboard(selected_ssid, password, symbols,
                                             uppercase, show_password, message);
                    screen = SCREEN_KEYBOARD;
                } else {
                    wifi_manager_start_scan();
                    render_scanning(can_exit);
                    screen = SCREEN_SCANNING;
                }
                continue;
            }
            if (screen == SCREEN_NETWORKS) {
                setup_action_t action = setup_input_scan_hit(
                    x, y, network_page, wifi_manager_network_count());
                if (action.type == SETUP_ACTION_RESCAN) {
                    network_page = 0;
                    wifi_manager_start_scan();
                    render_scanning(can_exit);
                    screen = SCREEN_SCANNING;
                } else if (action.type == SETUP_ACTION_PREVIOUS) {
                    --network_page;
                    render_networks(network_page, NULL, can_exit);
                } else if (action.type == SETUP_ACTION_NEXT) {
                    ++network_page;
                    render_networks(network_page, NULL, can_exit);
                } else if (action.type == SETUP_ACTION_NETWORK) {
                    const wifi_network_t *network = wifi_manager_network(action.network_index);
                    if (network) {
                        snprintf(selected_ssid, sizeof(selected_ssid), "%s", network->ssid);
                        password[0] = '\0';
                        message[0] = '\0';
                        interactive_connection = true;
                        if (network->authmode == WIFI_AUTH_OPEN) {
                            setup_ui_render_connecting(selected_ssid);
                            vTaskDelay(pdMS_TO_TICKS(200));
                            wifi_manager_stage_credentials_and_restart(selected_ssid, "");
                        } else {
                            symbols = false;
                            uppercase = false;
                            show_password = false;
                            setup_ui_render_keyboard(selected_ssid, password, symbols,
                                                     uppercase, show_password, NULL);
                            screen = SCREEN_KEYBOARD;
                        }
                    }
                }
            } else if (screen == SCREEN_KEYBOARD) {
                setup_action_t action = setup_input_keyboard_hit(x, y, symbols, uppercase);
                bool redraw_keyboard = false;
                bool redraw_password = false;
                switch (action.type) {
                    case SETUP_ACTION_CHARACTER:
                        append_character(password, sizeof(password), action.character);
                        redraw_password = true;
                        break;
                    case SETUP_ACTION_BACKSPACE: {
                        size_t length = strlen(password);
                        if (length) password[length - 1] = '\0';
                        redraw_password = true;
                        break;
                    }
                    case SETUP_ACTION_SHIFT:
                        uppercase = !uppercase;
                        redraw_keyboard = true;
                        break;
                    case SETUP_ACTION_SYMBOLS:
                        symbols = !symbols;
                        redraw_keyboard = true;
                        break;
                    case SETUP_ACTION_SPACE:
                        append_character(password, sizeof(password), ' ');
                        redraw_password = true;
                        break;
                    case SETUP_ACTION_SHOW_PASSWORD:
                        show_password = !show_password;
                        redraw_password = true;
                        break;
                    case SETUP_ACTION_CANCEL:
                        memset(password, 0, sizeof(password));
                        render_networks(network_page, NULL, can_exit);
                        screen = SCREEN_NETWORKS;
                        break;
                    case SETUP_ACTION_CONNECT:
                        setup_ui_render_connecting(selected_ssid);
                        vTaskDelay(pdMS_TO_TICKS(200));
                        wifi_manager_stage_credentials_and_restart(selected_ssid,
                                                                   password);
                        break;
                    default:
                        break;
                }
                if (redraw_keyboard) {
                    message[0] = '\0';
                    setup_ui_render_keyboard(selected_ssid, password, symbols,
                                             uppercase, show_password, NULL);
                } else if (redraw_password) {
                    message[0] = '\0';
                    setup_ui_render_password(password, show_password, NULL);
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }

    {
        char log_lines[FELICITY_WIFI_LOG_MAX_LINES][FELICITY_WIFI_LOG_LINE_MAX];
        uint32_t revision = 0;
        size_t log_count = wifi_manager_log_snapshot(
            log_lines, FELICITY_WIFI_LOG_MAX_LINES, &revision);
        render_connection_log(selected_ssid, log_lines, log_count, false, true,
                              can_exit);
        vTaskDelay(pdMS_TO_TICKS(1200));
    }
    memset(password, 0, sizeof(password));

    char ha_host[FELICITY_HA_HOST_MAX];
    device_settings_load_ha_host(ha_host, sizeof(ha_host));
    device_settings_prepare_api_url(ha_host, api_url, api_url_capacity);
    ESP_LOGI("wifi_setup", "Dashboard API: %s", api_url);
    nextion_show_page(DASH_PAGE_HOME);
}

void wifi_setup_configure_ha(char *api_url, size_t api_url_capacity)
{
    char ha_host[FELICITY_HA_HOST_MAX];
    device_settings_load_ha_host(ha_host, sizeof(ha_host));
    bool symbols = false;
    bool uppercase = false;
    setup_ui_render_api_keyboard(ha_host, symbols, uppercase,
                                 "DATA NOT AVAILABLE");
    while (true) {
        touch_event_t touch;
        if (!nextion_read_touch_event(&touch)) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }
        setup_ui_keyboard_touch_feedback(touch.x, touch.y, symbols,
                                         uppercase, touch.pressed);
        if (touch.pressed) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }
        setup_action_t action = setup_input_keyboard_hit(
            touch.x, touch.y, symbols, uppercase);
        const char *error = NULL;
        bool redraw_all = false;
        bool redraw_value = false;
        switch (action.type) {
            case SETUP_ACTION_CHARACTER:
                append_character(ha_host, sizeof(ha_host), action.character);
                redraw_value = true;
                break;
            case SETUP_ACTION_BACKSPACE: {
                size_t length = strlen(ha_host);
                if (length) ha_host[length - 1] = '\0';
                redraw_value = true;
                break;
            }
            case SETUP_ACTION_SHIFT:
                uppercase = !uppercase;
                redraw_all = true;
                break;
            case SETUP_ACTION_SYMBOLS:
                symbols = !symbols;
                redraw_all = true;
                break;
            case SETUP_ACTION_SHOW_PASSWORD:
                ha_host[0] = '\0';
                redraw_value = true;
                break;
            case SETUP_ACTION_CANCEL:
                device_settings_prepare_api_url(ha_host, api_url,
                                                api_url_capacity);
                nextion_show_page(DASH_PAGE_HOME);
                return;
            case SETUP_ACTION_CONNECT:
                if (device_settings_save_ha_host(ha_host)) {
                    device_settings_prepare_api_url(ha_host, api_url,
                                                    api_url_capacity);
                    nextion_show_page(DASH_PAGE_HOME);
                    return;
                }
                error = "INVALID ADDRESS";
                redraw_value = true;
                break;
            default:
                break;
        }
        if (redraw_all) {
            setup_ui_render_api_keyboard(ha_host, symbols, uppercase, error);
        } else if (redraw_value) {
            setup_ui_render_password(ha_host, true, error);
        }
    }
}
