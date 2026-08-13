idf_component_register(
    SRCS "app_main.c" "clock_sync.c" "dashboard_data.c" "device_update.c"
         "nextion.c" "nextion_protocol.c" "touch_parser.c"
         "wifi_manager.c" "wifi_setup.c" "setup_ui.c" "setup_input.c"
         "wifi_portal.c" "device_settings.c"
    INCLUDE_DIRS "."
    REQUIRES app_update esp_app_format esp_event esp_http_client esp_http_server
             esp_netif esp_wifi esp_driver_uart cjson mbedtls mdns nvs_flash esp_timer
)
