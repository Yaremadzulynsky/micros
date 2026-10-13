#ifndef MICROS_SUPPORT_NETWORK_H
#define MICROS_SUPPORT_NETWORK_H
#include "print.h"
#include <micros/network.h>
/* Implemented by network.cpp. */
void embedded_network_start();
bool embedded_network_online();
void embedded_network_poll(char *(*execute)(char *));
void embedded_network_identity(MicrosPrint &out);
void embedded_network_profiles(MicrosPrint &out);
bool embedded_network_profile(const char *, const char *);
bool embedded_network_profiles_set(const char *, const char *, const char *, const char *);
bool embedded_network_configure(const char *, const char *);
bool embedded_network_relay(const char *, unsigned, const char *);
void embedded_network_reboot_after_reply();
bool embedded_network_base_fetch(const char *, const char *);
bool embedded_network_base_fetching();
#endif
