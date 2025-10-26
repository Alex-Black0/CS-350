# CS-350

Reflection

Summarize the project and what problem it was solving:
The final project focused on designing and programming a smart thermostat prototype using a Raspberry Pi. The problem it solved was creating an embedded system capable of reading real-time temperature data, comparing it to a user-defined set point, and automatically responding through heating or cooling indicators. This prototype demonstrated how physical components—sensors, LEDs, buttons, and a display—can be integrated into a cohesive control system that simulates data transmission to a cloud server.

What did you do particularly well?
I did particularly well in structuring the code using a state machine, which made the system’s logic clear, maintainable, and predictable. I also ensured that each component (I²C sensor, GPIO buttons, PWM LEDs, UART output, and LCD display) was tested individually before integrating everything into the main system.

Where could you improve?
I could improve on initial hardware setup efficiency—especially verifying pin mapping and addressing before coding. Some debugging time was lost early in the project due to miswired components. In the future, I would plan wiring diagrams and verify hardware communication with test scripts before full integration.

What tools and/or resources are you adding to your support network?
I am adding the Raspberry Pi documentation, Adafruit CircuitPython libraries, and official GPIOZero references to my development toolkit. I also plan to continue using GitHub to store project revisions and document technical notes for future embedded development.

What skills from this project will be particularly transferable to other projects and/or coursework?
The most transferable skills include reading data via I²C, handling interrupts with GPIOZero, using PWM signals to drive analog-like LED effects, and managing system state using Python-based state machines. These are fundamental embedded programming techniques that apply directly to IoT, robotics, and automation projects.

How did you make this project maintainable, readable, and adaptable?
I followed best practices for code readability by adding clear comments, grouping related functions, and using descriptive variable names. Each peripheral initialization (I²C, UART, GPIO) is modularized, and constants are defined at the top of the script so hardware can be remapped easily. The code structure also supports future expansion, such as integrating Wi-Fi connectivity or data logging for cloud analytics.
