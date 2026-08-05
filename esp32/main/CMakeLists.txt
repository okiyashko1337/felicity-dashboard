idf_component_register(
    SRCS "app_main.c" "dashboard_data.c" "nextion.c" "touch_parser.c"
         "wifi_manager.c" "wifi_setup.c" "setup_ui.c" "setup_input.c"
         "wifi_portal.c" "device_settings.c"
    INCLUDE_DIRS "."
    REQUIRES esp_app_format esp_event esp_http_client esp_http_server esp_netif esp_wifi esp_driver_uart cjson mdns nvs_flash esp_timer
)
