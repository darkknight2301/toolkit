// include/mock_uart.hpp
//
// Mocked UART abstraction. Real validation frameworks often have a UART
// console (for sanity checks, debug logs, etc.) running alongside the NVMe
// command path. This class simulates that interface without touching any
// real hardware or serial port — it simply returns canned responses based
// on the input command, which the caller can validate with std::regex.

#ifndef NVME_POC_MOCK_UART_HPP
#define NVME_POC_MOCK_UART_HPP

#include <iostream>
#include <regex>
#include <string>

namespace nvmeLib {

class MockUart {
public:
    MockUart() : isOpen_(false) {}

    // Simulates opening the UART connection.
    void open() {
        isOpen_ = true;
        std::cout << "[MockUart] UART opened." << std::endl;
    }

    // Simulates closing the UART connection.
    void close() {
        isOpen_ = false;
        std::cout << "[MockUart] UART closed." << std::endl;
    }

    // Simulates sending a command over UART and receiving a response.
    //
    // cmd       - the command path/string sent to the UART (e.g. "/sys")
    // pattern   - a regex pattern the caller expects to find in the response
    // timeoutMs - mocked timeout value (unused functionally, kept for
    //             interface fidelity with the real framework)
    //
    // Returns the mocked response string. The caller is responsible for
    // matching `pattern` against the response if validation is desired.
    std::string send(const std::string& cmd,
                     const std::string& pattern,
                     uint32_t timeoutMs) {
        (void)pattern;
        (void)timeoutMs;

        std::cout << "[MockUart] send(\"" << cmd << "\")" << std::endl;

        // Mocked response table. In this POC, any "/sys"-style sanity
        // query returns a completed sanity status.
        std::string response;
        if (cmd == "/sys") {
            response = "Sanity : Completed";
        } else {
            response = "Unknown : N/A";
        }

        std::cout << "[MockUart] response: \"" << response << "\"" << std::endl;
        return response;
        }

        // Convenience helper: returns true if `pattern` is found in `response`.
        static bool matches(const std::string& response, const std::string& pattern) {
            std::regex re(pattern);
            return std::regex_search(response, re);
        }

        bool isOpen() const { return isOpen_; }

private:
    bool isOpen_;
};

} // namespace nvmelib

#endif // NVME_POC_MOCK_UART_HPP