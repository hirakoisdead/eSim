/* 18.Mar.2017 - RM - Cleaned up.*/
/* 20.June.2020 - BM - Added OS dependent includes*/
#define _GNU_SOURCE
#include <stdio.h>

#include <stdlib.h>
#include <stdint.h>
#include <unistd.h>
#include <sys/types.h>
#include <string.h>

#if defined(__linux__)
#include <sys/socket.h>
#include <netinet/in.h>
#include <netdb.h>
#include <arpa/inet.h>
#elif __APPLE__
#include <sys/socket.h>
#include <netinet/in.h>
#include <netdb.h>
#include <arpa/inet.h>
#elif _WIN32
#include <ws2tcpip.h>
#include <winsock2.h>
#include <eventsys.h>
#include <windows.h>
#endif

// Should be enough..
#define MAX_BUF_SIZE 4096

// Size of a VhpiString, i.e. the buffer the testbench hands us across
// VHPIDIRECT. MUST track c_vhpi_max_string_length in Utility_Package.vhdl:
// VhpiString is string(1 to c_vhpi_max_string_length), NUL-terminated by
// Pack_String_To_Vhpi_String, and the generated testbench declares every
// port's _v variable as a full VhpiString regardless of that port's width.
#define VHPI_MAX_STRING_LENGTH 1024

// Defualt port number

// unlikely to have more than 16 active
// threads talking to the TB?
#define DEFAULT_MAX_CONNECTIONS 65535

int DEFAULT_SERVER_PORT;

// Vhpi Functions.
void Vhpi_Initialize(int sock_port, char sock_ip[]); /* 26.Sept.2019 - RP */
void Vhpi_Exit(int sig);
void Vhpi_Listen();
void Vhpi_Send();
void Vhpi_Set_Port_Value(char *reg_name, char *reg_value, int port_width);
void Vhpi_Get_Port_Value(char *reg_name, char *reg_value, int port_width);
