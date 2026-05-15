Small Campus Edge Topology — Requirements and Acceptance Criteria

Purpose
- Generate a single eNSP topology XML that can be opened directly in Huawei eNSP to simulate a small campus edge network.
- The agent must output one file at: output/campus-network.xml
- The file must follow the latest .topo XML format with version="1.3.00.100".

Devices (exact names and models — do not add extras)
Create exactly 11 devices with these name/model pairs:
- R1 (AR2220)
- R2 (AR2220)
- FW1 (USG6000V)
- SW1 (S5700)
- SW2 (S5700)
- PC-A (PC)
- PC-B (PC)
- Server1 (Server)
- Internet (Cloud)
- AC1 (AC6005)
- AP1 (AP6050)

Connections (exactly 11 total)
Use interfacePair lineName exactly as specified for each connection:
- Serial (1 connection):
  - R1 <-> R2
- Copper (10 connections):
  - R1 <-> FW1
  - R2 <-> FW1
  - FW1 <-> SW1
  - FW1 <-> SW2
  - SW1 <-> PC-A
  - SW2 <-> PC-B
  - SW2 <-> Server1
  - SW1 <-> AC1
  - SW1 <-> AP1
  - R1 <-> Internet

Layout and grouping
- Use a grid-based auto layout starting near (100,100) with spacing ≈ 200px horizontally and ≈ 150px vertically. Device size can be assumed ~80x60px.
- Group logically:
  - Core zone (blue rectangle): R1, R2, FW1, SW1, SW2
  - Access zone (yellow rectangle): PC-A, PC-B, Server1, AC1, AP1
- Example grid positions (you may adjust slightly as needed while keeping group logic):
  - Row 1 (~y=100): R1 at (100,100), R2 at (300,100), Internet at (500,100)
  - Row 2 (~y=250): FW1 at (200,250), SW1 at (100,250), SW2 at (300,250)
  - Row 3 (~y=400): PC-A at (100,400), AC1 at (300,400), AP1 at (500,400), PC-B at (300,550), Server1 at (500,550)
- Set edit_left/edit_top to reasonable values relative to cx/cy (e.g., edit_left ≈ cx+27, edit_top ≈ cy+54).

Area boxes (shapes)
- Add at least two rectangle shapes (type="1"):
  - One blue rectangle with color="255" that encloses the core zone (R1, R2, FW1, SW1, SW2).
  - One yellow rectangle with color="16776960" that encloses the access zone (PC-A, PC-B, Server1, AC1, AP1).
- Use filloption="1" and reasonable upleftcorner/width/height to visually contain the devices.

Text labels (txttips)
- Add at least three txttips containing these exact strings (each string must appear at least once):
  - "VLAN10 - Users"
  - "VLAN20 - Servers"
  - "Serial link R1-R2 (DCE/DTE)"
- Place labels in readable positions within the canvas. Use fontname="Consolas", fontstyle="0", editsize="100", and readable colors (e.g., txtcolor="-16777216", txtbkcolor="-1" for transparent background).

Technical requirements for the .topo XML
- Root element:
  <topo version="1.3.00.100">
    <devices>...</devices>
    <lines>...</lines>
    <shapes>...</shapes>
    <txttips>...</txttips>
  </topo>
- Devices:
  - Exactly 11 <dev> elements, one for each required device name/model pair.
  - Each <dev> must have:
    - A unique UUID v4 in the id attribute (format 8-4-4-4-12 hex, e.g., 123e4567-e89b-12d3-a456-426614174000; case-insensitive).
    - name attribute matching the list above (e.g., name="R1").
    - model attribute matching the list above (e.g., model="AR2220").
    - Reasonable cx/cy coordinates and edit_left/edit_top offsets.
    - At least one <slot> child that matches the device model’s expected interface structure for eNSP.
- Lines:
  - Exactly 11 <line> elements under <lines>.
  - Each <line> references devices by UUID via srcDeviceID and destDeviceID.
  - Each <line> must contain exactly one <interfacePair> child with:
    - lineName="Serial" for the R1-R2 link.
    - lineName="Copper" for the 10 Ethernet links listed.
    - srcIndex/tarIndex may be set to 0 or other reasonable interface indices; coordinate attributes optional.
- Shapes:
  - At least two type="1" shapes:
    - One with color="255" (blue) covering core zone.
    - One with color="16776960" (yellow) covering access zone.
- Txttips:
  - At least three <txttip> elements whose content fields include the exact strings listed in the “Text labels” section.

Non-functional constraints
- Do not include any devices other than the 11 specified.
- Do not include any lines other than the 11 specified pairs.
- Do not include any image or non-text assets.
- Use only relative paths; write exactly one file to output/campus-network.xml.
- English-only text content (no non-English characters).

Acceptance criteria (used by automated checker)
The submission will be accepted if and only if:
1) File exists: output/campus-network.xml
2) XML validity:
   - Root tag is <topo version="1.3.00.100"> with sections <devices>, <lines>, <shapes>, <txttips>.
3) Devices:
   - Exactly 11 <dev> entries.
   - Each required device present exactly once with exact name/model pairs:
     R1(AR2220), R2(AR2220), FW1(USG6000V), SW1(S5700), SW2(S5700), PC-A(PC), PC-B(PC), Server1(Server), Internet(Cloud), AC1(AC6005), AP1(AP6050).
   - Each <dev> has id matching UUID v4 format and at least one <slot> child.
4) Lines:
   - Exactly 11 <line> elements.
   - One Serial connection present between R1 and R2 (order of src/dest may be either direction) with interfacePair lineName="Serial".
   - Ten Copper connections present (order-agnostic) with lineName="Copper" for these pairs:
     R1-FW1, R2-FW1, FW1-SW1, FW1-SW2, SW1-PC-A, SW2-PC-B, SW2-Server1, SW1-AC1, SW1-AP1, R1-Internet.
5) Shapes:
   - At least two rectangle shapes type="1"; one has color="255" (blue) and one has color="16776960" (yellow).
6) Txttips:
   - At least three labels exist and collectively include each exact substring:
     "VLAN10 - Users", "VLAN20 - Servers", "Serial link R1-R2 (DCE/DTE)".
7) No extra devices or lines beyond those explicitly requested.

Model-specific slot/interface reminders (for reference)
- AR2220 (R1, R2):
  <slot number="slot17" isMainBoard="1">
    <interface sztype="Ethernet" interfacename="GE" count="1"/>
    <interface sztype="Ethernet" interfacename="GE" count="2"/>
    <interface sztype="Serial" interfacename="Serial" count="2"/>
  </slot>
  <slot isMainBoard="0" id="3" type="521"/>
- USG6000V (FW1):
  <slot id="1">
    <interface category="Ethernet" type="GE" slotIndex="0" cardIndex="0" interfaceIndex="0"/>
    <interface category="Ethernet" type="GE" slotIndex="1" cardIndex="0" interfaceIndex="0"/>
    <interface category="Ethernet" type="GE" slotIndex="1" cardIndex="0" interfaceIndex="1"/>
    <interface category="Ethernet" type="GE" slotIndex="1" cardIndex="0" interfaceIndex="2"/>
    <interface category="Ethernet" type="GE" slotIndex="1" cardIndex="0" interfaceIndex="3"/>
    <interface category="Ethernet" type="GE" slotIndex="1" cardIndex="0" interfaceIndex="4"/>
    <interface category="Ethernet" type="GE" slotIndex="1" cardIndex="0" interfaceIndex="5"/>
    <interface category="Ethernet" type="GE" slotIndex="1" cardIndex="0" interfaceIndex="6"/>
  </slot>
- S5700 (SW1, SW2):
  <slot number="slot17" isMainBoard="1">
    <interface sztype="Ethernet" interfacename="GE" count="24"/>
  </slot>
- AC6005 (AC1):
  <slot number="slot17" isMainBoard="1">
    <interface sztype="Ethernet" interfacename="GE" count="8"/>
  </slot>
- AP6050 (AP1):
  <slot number="slot17" isMainBoard="1">
    <interface sztype="Ethernet" interfacename="GE" count="2"/>
  </slot>
- PC (PC-A, PC-B), Server (Server1), Cloud (Internet):
  Each device must have at least one <slot> with a single Ethernet interface (per their model format in eNSP).

Output location
- Write exactly one file to: output/campus-network.xml
- Do not write to any other path. Files outside output/ are ignored by the checker.