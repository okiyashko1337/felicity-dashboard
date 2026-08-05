idf_component_register(
    SRCS "app_main.c" "dashboard_data.c" "device_settings.c" "nextion.c"
         "touch_parser.c" "wifi_provisioning.c"
    INCLUDE_DIRS "."
    REQUIRES esp_eth esp_event esp_http_client esp_http_server esp_netif esp_wifi
             esp_driver_gpio esp_driver_uart cjson lwip nvs_flash
)
