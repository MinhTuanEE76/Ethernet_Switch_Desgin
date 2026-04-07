#include "http_client.h"
#include "esp_log.h"
#include "esp_http_client.h"
#include "cJSON.h"
#include "time_sync.h"
#include "scheduler.h"
#include "relay.h"
#include <string.h>
#include <stdlib.h>
#include <time.h>

#define API_BASE "http://172.20.10.2:8018/api/switch"
#define NODE_ID 1

typedef struct {
    char *data;
    int len;
    int cap;
} http_buf_t;

struct tm g_time_server = {0};

// Nhận dữ liệu từ http vào bộ đệm động
static esp_err_t _http_event_handler(esp_http_client_event_t *evt) {
    http_buf_t *buf = (http_buf_t *)evt->user_data;
    switch (evt->event_id) {
        case HTTP_EVENT_ON_DATA:
            if (!buf->data) {
                buf->cap = evt->data_len + 1;
                buf->data = malloc(buf->cap);
                buf->len = 0;
            }
            if (buf->len + evt->data_len + 1 > buf->cap) {
                buf->cap = buf->len + evt->data_len + 1;
                buf->data = realloc(buf->data, buf->cap);
            }
            memcpy(buf->data + buf->len, evt->data, evt->data_len);
            buf->len += evt->data_len;
            buf->data[buf->len] = '\0';
            break;
        default: break;
    }
    return ESP_OK;
}

// Xử lý json, đồng bộ time, cập nhật relay, schedule, auto_off
static void parse_and_apply_config(const char *json_str) {
    ESP_LOGD("HTTP_CLIENT","Parsing anh apply config");
    if (!json_str) return;
    cJSON *json = cJSON_Parse(json_str);
    if (!json) return;


    // Đồng bộ thời gian
    ESP_LOGD("\nHTTP_CLIENT","Being Time_Sync for esp32 ");
    cJSON *current_time = cJSON_GetObjectItem(json, "current_time");
    if (current_time) {
        // seconds_in_day
        cJSON *seconds_in_day = cJSON_GetObjectItem(current_time, "seconds_in_day");
        if (seconds_in_day && cJSON_IsNumber(seconds_in_day)) {
            time_sync_set_server_seconds(seconds_in_day->valueint);
        }

        // Parse timestamp dạng chuỗi ISO 8601
        ESP_LOGD("\nHTTP_CILENT","Parsing timestamp ISO 8601");
        cJSON *timestamp = cJSON_GetObjectItem(current_time, "timestamp");
        if (timestamp && cJSON_IsString(timestamp)) {
            // format: "2025-09-30T10:43:15.294463+07:00"
            int year, mon, mday, hour, min, sec;
            if (sscanf(timestamp->valuestring, "%d-%d-%dT%d:%d:%d", &year, &mon, &mday, &hour, &min, &sec) == 6) {
                g_time_server.tm_year = year;
                g_time_server.tm_mon  = mon;
                g_time_server.tm_mday = mday;
                g_time_server.tm_hour = hour;
                g_time_server.tm_min  = min;
                g_time_server.tm_sec  = sec;
                // Có thể bổ sung tm_wday nếu muốn, lấy từ cJSON bên dưới
                cJSON *weekday = cJSON_GetObjectItem(current_time, "weekday");
                if (weekday && cJSON_IsNumber(weekday)) {
                    g_time_server.tm_wday = weekday->valueint; // 0: Chủ nhật, 1: Thứ hai, ...
                }
                ESP_LOGI("\nCURRENT TIME","%dh-%dmin-%dsec  %d-%d-%d",g_time_server.tm_hour,g_time_server.tm_min,g_time_server.tm_sec
                                                            ,g_time_server.tm_year,g_time_server.tm_mon,g_time_server.tm_mday
                                                        );
            }
        }
    }




// Xử lý trạng thái relay theo lệnh server, và auto_off_timer ngoài schedule
    // Xử lý trạng thái relay theo lệnh server, và auto_off_timer ngoài schedule
    cJSON *status = cJSON_GetObjectItem(json, "status");
    cJSON *auto_off_timer = cJSON_GetObjectItem(json, "auto_off_timer");

    if (status && cJSON_IsString(status)) {
        bool should_on = (strcmp(status->valuestring, "ON") == 0);
        if (should_on != relay_get()) {
            ESP_LOGI("HTTP_CLIENT", "Server command status: %s", should_on ? "ON" : "OFF");
            relay_set(should_on);
        }

        // Nếu có auto_off_timer từ server (ngoài schedule)
        if (should_on && auto_off_timer && !cJSON_IsNull(auto_off_timer)) {
            ESP_LOGI("AUTO_OFF_TIMER", "Detect auto_off_timer from server (not schedules)");

            cJSON *minutes = cJSON_GetObjectItem(auto_off_timer, "minutes");
            cJSON *start_time = cJSON_GetObjectItem(auto_off_timer, "start_time");

            int autooff_min = (minutes && cJSON_IsNumber(minutes)) ? minutes->valueint : -1;
            const char *start_time_str = (start_time && cJSON_IsString(start_time)) ? start_time->valuestring : NULL;

            // In log để tiện debug
            ESP_LOGI("HTTP_CLIENT", "auto_off_timer raw: minutes=%d, start_time=%s", autooff_min, start_time_str ? start_time_str : "NULL");

            if (autooff_min > 0 && start_time_str) {
                // Cắt bỏ phần .xxx hoặc timezone nếu có để sscanf chính xác
                char start_buf[32];
                strncpy(start_buf, start_time_str, sizeof(start_buf) - 1);
                start_buf[sizeof(start_buf) - 1] = '\0';
                char *dot = strchr(start_buf, '.');
                if (dot) *dot = '\0'; // Cắt tại dấu chấm (bỏ milli giây và timezone)

                struct tm start_tm = {0};
                int ret = sscanf(start_buf, "%d-%d-%dT%d:%d:%d",
                                &start_tm.tm_year, &start_tm.tm_mon, &start_tm.tm_mday,
                                &start_tm.tm_hour, &start_tm.tm_min, &start_tm.tm_sec);
                    
                ESP_LOGI("\nPARSE in  auto_off_timer","%dh-%dmin-%dsec",start_tm.tm_hour,start_tm.tm_min,start_tm.tm_sec);

                if (ret == 6) {
                    start_tm.tm_year -= 1900;
                    start_tm.tm_mon  -= 1;
                    int start_epoch = start_tm.tm_hour*60*60 + start_tm.tm_min*60 + start_tm.tm_sec;
                    int off_epoch = start_epoch + autooff_min * 60;
                    int now_epoch = time_sync_now_seconds();
        

                    ESP_LOGI("HTTP_CLIENT", "start_epoch=%d, autooff_min=%d , now_epoch=%d", start_epoch, autooff_min,now_epoch);

                    if (off_epoch > now_epoch && relay_get()) {
                        int now_s = time_sync_now_seconds();
                        int seconds_to_autooff = (off_epoch - now_epoch);
                        int expire_in_s = now_s + seconds_to_autooff;
                        scheduler_set_auto_off_expire(expire_in_s);
                        ESP_LOGI("HTTP_CLIENT", "auto_off_timer: relay will be off after %d seconds!,expire_time:%d",
                                                                                     seconds_to_autooff,expire_in_s);
                    } else {
                        ESP_LOGW("HTTP_CLIENT", "auto_off_timer expired or invalid, ignoring auto off setup.");
                    }
                } else {
                    ESP_LOGE("HTTP_CLIENT", "Parse start_time failed! start_buf: %s, original: %s", start_buf, start_time_str);
                }
            } else {
                ESP_LOGW("HTTP_CLIENT", "auto_off_timer missing or malformed fields (minutes/start_time)");
            }
        }
    }


    // // Xử lý trạng thái relay theo lệnh server, và auto_off_timer ngoài schedule
    // cJSON *status = cJSON_GetObjectItem(json, "status");
    // cJSON *auto_off_timer = cJSON_GetObjectItem(json, "auto_off_timer");
    // if (status && cJSON_IsString(status)) {
    //     bool should_on = (strcmp(status->valuestring, "ON") == 0);
    //     if (should_on != relay_get()) {
    //         ESP_LOGI("HTTP_CLIENT", "Server command status: %s", should_on ? "ON" : "OFF");
    //         relay_set(should_on);
    //     }
    //     // Nếu có auto_off_timer từ server (ngoài schedule)
    //     if (should_on && auto_off_timer && !cJSON_IsNull(auto_off_timer)) {
    //         ESP_LOGD("\nAUTO_OFF_TIMER","Dectect auto off timer from server (not schedules)");
    //         cJSON *minutes = cJSON_GetObjectItem(auto_off_timer, "minutes");
    //         cJSON *start_time = cJSON_GetObjectItem(auto_off_timer, "start_time");
    //         if (minutes && cJSON_IsNumber(minutes) && start_time && cJSON_IsString(start_time)) {
    //             struct tm start_tm = {0};
    //             sscanf(start_time->valuestring, "%d-%d-%dT%d:%d:%d",
    //                 &start_tm.tm_year, &start_tm.tm_mon, &start_tm.tm_mday,
    //                 &start_tm.tm_hour, &start_tm.tm_min, &start_tm.tm_sec);
    //             start_tm.tm_year -= 1900; start_tm.tm_mon -= 1;
    //             time_t start_epoch = mktime(&start_tm);
    //             int autooff_min = minutes->valueint;
    //             time_t off_epoch = start_epoch + autooff_min*60;
    //             time_t now_epoch = time(NULL);
    //             ESP_LOGI("DEBUG", "start_epoch=%ld, now_epoch=%ld, autooff_min=%d", start_epoch, now_epoch, autooff_min);
    //             if (off_epoch > now_epoch && relay_get()) {
    //                 int now_s = time_sync_now_seconds();
    //                 int seconds_to_autooff = (int)(off_epoch - now_epoch);
    //                 int expire_in_s = now_s + seconds_to_autooff;
    //                 scheduler_set_auto_off_expire(expire_in_s);
    //                 ESP_LOGI("\nHTTP_CLIENT", "auto_off_timer: relay will be off after %d seconds!", seconds_to_autooff);
    //             }
    //         }
    //     }
    // }

    // Xử lý schedule lấy từ server
    cJSON *schedules_array = cJSON_GetObjectItem(json, "schedules");
    if (schedules_array && cJSON_IsArray(schedules_array)) {
        schedule_t tmp[SCHED_MAX];
        int cnt = 0;
        cJSON *s;
        cJSON_ArrayForEach(s, schedules_array) {
            if (cnt >= SCHED_MAX) break;
            cJSON *id = cJSON_GetObjectItem(s, "id");
            cJSON *action = cJSON_GetObjectItem(s, "action");
            cJSON *active = cJSON_GetObjectItem(s, "active");
            cJSON *auto_off = cJSON_GetObjectItem(s, "auto_off");
            cJSON *repeat_type = cJSON_GetObjectItem(s, "repeat_type");
            cJSON *time = cJSON_GetObjectItem(s, "time");
            if (!id || !action || !active || !time) continue;
            tmp[cnt].id = id->valueint;
            strncpy(tmp[cnt].action, cJSON_IsString(action) ? action->valuestring : "on", sizeof(tmp[cnt].action)-1);
            tmp[cnt].action[sizeof(tmp[cnt].action)-1] = '\0';
            tmp[cnt].active = cJSON_IsNumber(active) ? active->valueint : 1;
            tmp[cnt].auto_off = (auto_off && cJSON_IsNumber(auto_off)) ? auto_off->valueint : 0;
            strncpy(tmp[cnt].repeat_type, cJSON_IsString(repeat_type) ? repeat_type->valuestring : "once", sizeof(tmp[cnt].repeat_type)-1);
            tmp[cnt].repeat_type[sizeof(tmp[cnt].repeat_type)-1] = '\0';
            tmp[cnt].time_seconds = cJSON_IsNumber(time) ? time->valueint : 0;
            cnt++;
        }
        scheduler_set_list(tmp, cnt);
    }
    cJSON_Delete(json);
}

void http_client_init(void) {}

void http_poll_config(void) {
    char url[256];
    snprintf(url, sizeof(url), API_BASE "/%d", NODE_ID);
    http_buf_t buf = {0};
    esp_http_client_config_t config = {
        .url = url,
        .method = HTTP_METHOD_GET,
        .event_handler = _http_event_handler,
        .user_data = &buf,
        .timeout_ms = 5000,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    esp_err_t err = esp_http_client_perform(client);
    if (err == ESP_OK && buf.data) {
        parse_and_apply_config(buf.data);
    }
    if (buf.data) free(buf.data);
    esp_http_client_cleanup(client);
}

void http_update_status(bool relay_on, int uptime_minutes) {
    char url[256];
    snprintf(url, sizeof(url), API_BASE "/%d/status", NODE_ID);
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "status", relay_on ? "ON" : "OFF");
    cJSON_AddNumberToObject(root, "uptime", uptime_minutes);
    char *payload = cJSON_PrintUnformatted(root);

    http_buf_t buf = {0};
    esp_http_client_config_t config = {
        .url = url,
        .method = HTTP_METHOD_POST,
        .event_handler = _http_event_handler,
        .user_data = &buf,
        .timeout_ms = 5000,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, payload, strlen(payload));
    esp_http_client_perform(client);

    if (payload) free(payload);
    if (buf.data) free(buf.data);
    cJSON_Delete(root);
    esp_http_client_cleanup(client);
}