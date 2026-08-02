idf_component_register(
    SRCS "app_main.c" "dashboard_data.c" "nextion.c" "touch_parser.c"
    INCLUDE_DIRS "."
    REQUIRES esp_event esp_http_client esp_netif esp_wifi esp_driver_uart cjson nvs_flash
)
