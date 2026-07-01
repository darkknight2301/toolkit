#include<chrono>
#include<iostream>
#include<thread>
#include "power_cycle.hpp"
using namespace std;

namespace nvmeutil
{
    void power_cycle(ssdcommon::PowRelay& relay)
    {
        cout<<"[PowerCycle] POWERING OFF... "<<endl;
        relay.off();

        this_thread::sleep_for(chrono::milliseconds(500));

        cout<<"[PowerCycle] POWERING ON...."<<endl;
        relay.on();
    }
}