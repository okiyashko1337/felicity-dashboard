#include "wifi_provisioning.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

static const char *TAG = "wifi_setup";
static EventGroupHandle_t setup_events;
static const EventBits_t SETTINGS_SAVED = BIT0;

static const char SETUP_PAGE[] =
    "<!doctype html><meta name=viewport content='width=device-width'>"
    "<style>body{font:18px system-ui;max-width:32rem;margin:3rem auto;padding:1rem;"
    "background:#041712;color:#eee}label{display:block;margin:1rem 0}input{width:100%;"
    "box-sizing:border-box;padding:.7rem;font-size:1rem}button{padding:.8rem 1.2rem;"
    "font-size:1rem;background:#34d399;border:0;border-radius:.4rem}</style>"
    "<h1>Felicity setup</h1><form method=post action=/save>"
    "<label>Wi-Fi network<input name=ssid maxlength=32 required></label>"
    "<label>Wi-Fi password<input name=password type=password maxlength=64></label>"
    "<label>Raspberry API<input name=api value='http://192.168.13.126:8000' required></label>"
    "<button>Save and connect</button></form>";

static void url_decode(char *value)
{
    char *read = value;
    char *write = value;
    while (*read) {
        if (*read == '+') {
            *write++ = ' ';
            read++;
        } else if (*read == '%' && isxdigit((unsigned char)read[1]) &&
                   isxdigit((unsigned char)read[2])) {
            char hex[3] = {read[1], read[2], 0};
            *write++ = (char)strtol(hex, NULL, 16);
            read += 3;
        } else {
            *write++ = *read++;
        }
    }
    *write = '\0';
}

static bool form_value(const char *body, const char *key, char *output, size_t capacity)
{
    if (httpd_query_key_value(body, key, output, capacity) != ESP_OK) return false;
    url_decode(output);
    return true;
}

static esp_err_t setup_get(httpd_req_t *request)
{
    httpd_resp_set_type(request, "text/html; charset=utf-8");
    return httpd_resp_send(request, SETUP_PAGE, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t setup_save(httpd_req_t *request)
{
    device_settings_t *settings = request->user_ctx;
    if (request->content_len <= 0 || request->content_len > 512) {
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST, "Invalid form");
    }
    char *body = calloc(1, (size_t)request->content_len + 1);
    if (!body) return httpd_resp_send_500(request);
    size_t total = 0;
    while (total < (size_t)request->content_len) {
        int received = httpd_req_recv(request, body + total,
                                      (size_t)request->content_len - total);
        if (received == HTTPD_SOCK_ERR_TIMEOUT) continue;
        if (received <= 0) break;
        total += (size_t)received;
    }
    bool valid = total == (size_t)request->content_len &&
                 form_value(body, "ssid", settings->wifi_ssid,
                            sizeof(settings->wifi_ssid)) &&
                 form_value(body, "password", settings->wifi_password,
                            sizeof(settings->wifi_password)) &&
                 form_value(body, "api", settings->api_base_url,
                            sizeof(settings->api_base_url)) &&
                 settings->wifi_ssid[0] && settings->api_base_url[0];
    free(body);
    if (!valid || !device_settings_save(settings)) {
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST,
                                   "Could not save settings");
    }
    httpd_resp_set_type(request, "text/html; charset=utf-8");
    httpd_resp_sendstr(request,
                       "<h1>Saved</h1><p>Felicity is restarting and connecting.</p>");
    xEventGroupSetBits(setup_events, SETTINGS_SAVED);
    return ESP_OK;
}

void wifi_provisioning_run(device_settings_t *settings)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_ap();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    uint8_t mac[6];
    ESP_ERROR_CHECK(esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP));
    wifi_config_t access_point = {0};
    snprintf((char *)access_point.ap.ssid, sizeof(access_point.ap.ssid),
             "Felicity-Setup-%02X%02X", mac[4], mac[5]);
    access_point.ap.ssid_len = strlen((char *)access_point.ap.ssid);
    access_point.ap.channel = 1;
    access_point.ap.max_connection = 2;
    access_point.ap.authmode = WIFI_AUTH_OPEN;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &access_point));
    ESP_ERROR_CHECK(esp_wifi_start());

    setup_events = xEventGroupCreate();
    ESP_ERROR_CHECK(setup_events ? ESP_OK : ESP_ERR_NO_MEM);
    httpd_config_t server_config = HTTPD_DEFAULT_CONFIG();
    httpd_handle_t server = NULL;
    ESP_ERROR_CHECK(httpd_start(&server, &server_config));
    httpd_uri_t root = {.uri = "/", .method = HTTP_GET, .handler = setup_get};
    httpd_uri_t save = {
        .uri = "/save", .method = HTTP_POST, .handler = setup_save,
        .user_ctx = settings,
    };
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &root));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &save));
    ESP_LOGW(TAG, "Setup mode: connect to %s and open http://192.168.4.1",
             access_point.ap.ssid);
    xEventGroupWaitBits(setup_events, SETTINGS_SAVED, pdFALSE, pdTRUE, portMAX_DELAY);
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
}
