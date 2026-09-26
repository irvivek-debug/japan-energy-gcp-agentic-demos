# Interlock Rationale Sheet (edge control loop)

Document IL-ATS-014, revision 3 (2026-06-15). Owner: Utilities engineering. Fictional document for a concept demo.

## Section 1 Principle
The edge controller evaluates every requested action against hard interlocks before anything moves. Cloud software proposes; the edge decides with live PLC state; a person confirms. Hard interlocks reject. Soft interlocks limit or stage the action. Rule ids are the ones in the interlock_rules table.

## Section 2 Clean-room air (IR-CR-01, IR-CR-02)
Clean rooms need their design air-change rate and a positive pressure cascade from production zones to corridors. Cutting airflow raises particle counts within minutes; exposed SiC die and substrates lose yield. Production-zone units stay at 100 % while product is exposed. Support-zone units may trim to 85 %; the edge keeps a 3 % margin above the floor. Switching clean-room HVAC off is always rejected.

## Section 3 Compressed air (IR-CA-01, IR-CA-02, IR-CA-03)
Line actuators and clean-room isolation valves fault below 0.60 MPa at the far end of the header. The header must keep N-1 redundancy: available capacity minus the largest unit covers plant demand. A unit in standby (auto-start ready) still counts as available; an isolated unit does not. The header set-point may be trimmed only to 0.65 MPa because the far end sees about 0.03 MPa less. Switching all compressors off collapses header pressure in seconds and is always rejected.

## Section 4 Furnaces (IR-FN-01, IR-FN-02, IR-FN-03)
Sintering and reflow profiles are non-interruptible. Once sinter paste is printed the batch is committed at the PLC and its pot-life clock is running; the edge will not defer or shed it. An idle furnace may drop to standby only if it can reheat (90 minutes) before its next batch.

## Section 5 Chilled water and thermal storage (IR-CH-01, IR-CH-02, IR-CH-03)
Chilled-water supply may rise to 8.5 C at most; above that the clean room loses humidity control. Thermal storage keeps a 15 % reserve for a chiller-trip ride-through. At least two chillers stay online.

## Section 6 Wastewater (IR-WW-01)
Lift pumps may hold for at most 60 minutes before the pit reaches its high alarm, which is a permit condition.

## Section 7 Battery (IR-BS-01, IR-BS-02, IR-BS-03)
The battery stays within 10-95 % state of charge and 4,000 kW, and set-points ramp at no more than 2,000 kW per minute.
