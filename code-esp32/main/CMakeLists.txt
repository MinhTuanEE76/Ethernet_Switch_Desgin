idf_component_register(SRCS "Ethernet.c"
                    INCLUDE_DIRS "."
                    REQUIRES http_client time_sync scheduler relay wifi_manager)
