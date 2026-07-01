#ifndef POW_RELAY_HPP
#define POW_RELAY_HPP

#include <iostream>
// #include "power_supply_controllable.hpp"

namespace ssdcommon {

class PowRelay : public PowerSupplyControllable {

public:
    PowRelay() = default;
    virtual ~PowRelay(void) = default;

    void on() override {
        std::cout << "[Relay] Power ON" << std::endl;
    }

    void off(void) override {
        std::cout << "[Relay] Power OFF" << std::endl;
    }

    void open(const char* devname) {
        std::cout << "[Relay] Open Device : " << devname << std::endl;
    }

    void close() {
        std::cout << "[Relay] Close Device" << std::endl;
    }

    int cur() {
        return 0;
    }
};

} // namespace ssdcommon

#endif