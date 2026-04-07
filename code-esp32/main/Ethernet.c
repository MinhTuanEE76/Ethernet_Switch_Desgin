#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "wifi_manager.h"
#include "http_client.h"
#include "relay.h"
#include "scheduler.h"
#include "time_sync.h"

static void task_poll_server(void *pv) {
    
    while (1) {
        ESP_LOGI("\nTASK_POLL_SERVER", "Polling server for configuration...");
        http_poll_config();
        vTaskDelay(pdMS_TO_TICKS(2000)); // lấy cấu hình mỗi 5s
    }
}

static void task_scheduler(void *pv) {
    while (1) {
        ESP_LOGI("\nSCHEDULER_TASK","Scheduler is running!!!");
        scheduler_check_and_run();
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

static void task_status_report(void *pv) {
    float uptime_minutes = 0;
    bool relay_last = relay_get();
    while (1) {
        ESP_LOGI("\nTASK_STATUS_REPORT", "ESP32 is posting status to server");
        vTaskDelay(pdMS_TO_TICKS(30000));
        bool relay_now = relay_get();
        if (relay_now) {
            uptime_minutes += 0.5; // mỗi 30s cộng nửa phút
        }
        http_update_status(relay_now, (int)uptime_minutes);
        relay_last = relay_now;
        ESP_LOGI("\nSTATUS_REPORT", "Status sent: %s, uptime: %.1f min", relay_last ? "ON" : "OFF", uptime_minutes);
    }
}

void app_main(void) {
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }
    esp_log_level_set("*", ESP_LOG_DEBUG);
    relay_init();
    scheduler_init();
    wifi_init_sta();
    ESP_LOGI("INFORM","Config wifi have finished");
    http_client_init();

    ESP_LOGI("INFORM","Create Task");

    xTaskCreate(task_poll_server, "poll_server", 8192, NULL, 5, NULL);
    xTaskCreate(task_scheduler, "scheduler", 4096, NULL, 4, NULL);
    xTaskCreate(task_status_report, "status_report", 4096, NULL, 6, NULL);
    xTaskCreate(scheduler_auto_off_task, "auto_off_task", 2048, NULL, 3, NULL);

    ESP_LOGI("MAIN", "Application started");
}