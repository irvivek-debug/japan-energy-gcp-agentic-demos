# Demand-Response Contract Summary (aggregator agreement)

Agreement DR-KANTO-2026-117 between the plant and its aggregator, summer season July to September 2026. Fictional summary for a concept demo.

## Section 1 Capacity and dispatch
Contracted reduction capacity is 3,000 kW. The aggregator may dispatch events on the day, normally at least 3 hours ahead, for windows of up to 3 hours between 13:00 and 21:00. The aggregator re-nominates the plant's 30-minute plan for the event window.

## Section 2 Payments
Availability payment: 650 JPY per kW-month of contracted capacity (July to September). Energy payment: 45 JPY per delivered kWh, capped at the requested kWh. Penalty: 60 JPY per kWh short of the requested kWh.

## Section 3 Measurement and baseline
Delivery is measured at the 66 kV receiving-point meter as baseline minus actual import, averaged over the event. The baseline is "High 4 of 5": the 5 most recent eligible weekdays before the event (weekends, public holidays, plant shutdown days and earlier event days excluded), keeping the 4 with the highest load over the event window, averaged slot by slot.

## Section 4 Same-day adjustment
The baseline is adjusted by the average difference between the event day and the selected days over the 4 slots that end 1 hour before the event starts. The adjustment uses load net of battery charging, so charging before an event cannot inflate the baseline.

## Section 5 Behind-the-meter storage
Battery discharge behind the receiving point counts toward delivery because it lowers receiving-point import. Routine battery discharge on non-event days remains part of the baseline.
