#include "scheduler.h"
#include "relay.h"
#include "time_sync.h"
#include "esp_log.h"
#include <string.h>
#include <time.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "http_client.h"

static schedule_t schedules[SCHED_MAX];
static int schedule_count = 0;
static SemaphoreHandle_t auto_off_mutex = NULL;//mutex de dam bao quyenn truy cap critical section
static int global_auto_off_expire_sec = -1;

extern struct tm g_time_server;

// Helper: chuyển struct tm thành kiểu ngày YYYYMMDD
static int get_yyyymmdd(const struct tm *t) {
    return (t->tm_year + 1900)*10000 + (t->tm_mon+1)*100 + t->tm_mday;
}

// Init
void scheduler_init(void) {
    schedule_count = 0;
    memset(schedules, 0, sizeof(schedules));
    if (!auto_off_mutex)
        auto_off_mutex = xSemaphoreCreateMutex();
    global_auto_off_expire_sec = -1;
}

// Nhận danh sách schedule mới
void scheduler_set_list(const schedule_t *list, int count) {
    if (count > SCHED_MAX) count = SCHED_MAX;
    memcpy(schedules, list, count * sizeof(schedule_t));
    schedule_count = count;
    for (int i = 0; i < count; ++i) {
        schedules[i].last_trigger_date = 0;
    }
    //scheduler_clear_auto_off();
    ESP_LOGI("SCHEDULER", "Loaded %d schedules", count);
}

/*
 * Kiểm tra từng schedule, thực thi action đúng điều kiện.
 * Có thể bổ sung thêm loại lặp lạ hơn tùy ý.
 */
void scheduler_check_and_run(void) {
    ESP_LOGI("\nSCHEDULER CHECK & RUN","Checking schedules");
    time_t t_raw;
    struct tm *tinfo;
    int now_s = time_sync_now_seconds();
    if (now_s < 0) return;
    time(&t_raw);
    tinfo = localtime(&t_raw);
    int today = get_yyyymmdd(tinfo);

    for (int i = 0; i < schedule_count; ++i) {
        schedule_t *s = &schedules[i];
        if (!s->active) continue;
        bool match_repeat = false;
        if (strcmp(s->repeat_type, "once") == 0) {
            match_repeat = (s->last_trigger_date == 0);
        } else if (strcmp(s->repeat_type, "daily") == 0) {
            match_repeat = (s->last_trigger_date != today);
        } else if (strcmp(s->repeat_type, "weekends") == 0 && 
            (g_time_server.tm_wday == 0 || g_time_server.tm_wday == 6)) {
            match_repeat = (s->last_trigger_date != today);
        } else if (strcmp(s->repeat_type, "weekdays") == 0 && 
            (g_time_server.tm_wday != 0 && g_time_server.tm_wday != 6)) {
            match_repeat = (s->last_trigger_date != today);
        }
        if (match_repeat && s->last_trigger_date != today) {
            if (now_s >= s->time_seconds && now_s < s->time_seconds + 5) {
                bool is_on = strcasecmp(s->action, "on") == 0;
                relay_set(is_on);
                http_update_status(relay_get(),1);
                s->last_trigger_date = today;
                ESP_LOGI("SCHEDULER", "Trigger schedule id %d, action=%s", s->id, s->action);
                if (is_on && s->auto_off > 0) {
                    int expire = now_s + s->auto_off * 60;
                    scheduler_set_auto_off_expire(expire);
                    ESP_LOGI("SCHEDULER", "Auto-off: %d min", s->auto_off);
                }
            }
        }
    }
}

// Auto-off relay bởi timer ngoài hoặc từ schedule
void scheduler_set_auto_off_expire(int sec) {
    if (auto_off_mutex && xSemaphoreTake(auto_off_mutex, 10/portTICK_PERIOD_MS)) {
        global_auto_off_expire_sec = sec;
        ESP_LOGI("\nEXPIRE_TIME","passed argument %d to set expire",global_auto_off_expire_sec);
        xSemaphoreGive(auto_off_mutex);
    }
}

void scheduler_clear_auto_off(void) {
    if (auto_off_mutex && xSemaphoreTake(auto_off_mutex, 10/portTICK_PERIOD_MS)) {
        global_auto_off_expire_sec = -1;
        xSemaphoreGive(auto_off_mutex);
    }
}

int scheduler_get_auto_off_expire(void) {
    int v = -1;
    if (auto_off_mutex && xSemaphoreTake(auto_off_mutex, 10/portTICK_PERIOD_MS)) {
        v = global_auto_off_expire_sec;
        ESP_LOGI("\nGLOBAL_AUTO_OFF_EXPIRE_SEC","value of global_auto_off_expire_sec = %d",v);
        xSemaphoreGive(auto_off_mutex);
    }
    return v;
}

// Task auto-off: kiểm tra mỗi giây, đến thời hạn sẽ tắt relay
void scheduler_auto_off_task(void *pv) {
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(1000));
        int expire = scheduler_get_auto_off_expire();
        ESP_LOGI("\nAUTO_OFF_TASK","getted expire from get_auto_off_expire");
        if (expire < 0){
            ESP_LOGI("AUTO_OFF_TASK","Chua co lich auto_off de thuc thi");
            continue;
        } 
        int now = time_sync_now_seconds();
        if (now < 0){
            ESP_LOGW("AUTO_OFF_TASK","Error Time Sync");
            continue;
        } 
        if (now >= expire) {
            ESP_LOGI("AUTO_OFF_TASK", "Detect auto_off time. Auto-off relay running!");
            relay_set(false);
            scheduler_clear_auto_off();
            http_update_status(relay_get(),0);
        }
        else{
            ESP_LOGI("WAITING_AUTO_OFF","watting time about %d sec",expire-now);
        }
    }
}