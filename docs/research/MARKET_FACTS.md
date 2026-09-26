# Japanese Electricity Market: Fact Sheet for Simulator Parameterization

**As of:** 2026-09-26 · **Scope:** JEPX spot/intraday, imbalance, balancing market, TEPCO-area retail cost stack, non-fossil certificates, demand, flexibility, TEPCO EP, Mitsubishi Electric, Google tech, battery economics.
**Use:** to parameterize realistic synthetic data and simulators for three GCP concept demos: (1) TEPCO Energy Partner retail/VPP, (2) Mitsubishi Electric factory edge-to-grid, (3) AlphaEvolve pricing/trading optimization lab.

**Tags**
- **[VERIFIED]**: read directly in the cited primary or credible source.
- **[VERIFIED] (computed)**: calculated by the analyst from official primary datasets that were downloaded (JEPX 30-min spot and intraday CSVs, the imbalance central-system CSVs, and TEPCO PG area supply-demand CSVs). The method is stated.
- **(secondary)**: a credible secondary source (trade press or consultancy) where no primary source was reachable.
- **[ESTIMATE]**: analyst inference or a snippet-only source. The basis is always stated. Never use these as reported facts.

**Conventions:** JPY; fiscal year (FY) = April–March; 30-minute slots are numbered 1–48 from 00:00 JST; 万kW = 10 MW; 億kWh = 0.1 TWh. Tariff figures are tax-inclusive unless noted.

---

## 1. JEPX day-ahead spot market (スポット市場 / 翌日市場)

### 1.1 Market structure (rules)

- [VERIFIED] **Products:** each delivery day is split into **48 products of 30 minutes** (hh:00–hh:30, hh:30–hh+1:00). Source: JEPX Trading Rules (取引規程) Art. 14. https://www.jepx.jp/electricpower/outline/pdf/tr_rules.pdf
- [VERIFIED] **Bidding window / gate closure:** bids accepted from **00:00 eleven days before delivery until 10:00 on the day before delivery**. Bids can be changed or cancelled any time inside the window. Source: 取引規程 Art. 16. (same URL)
- [VERIFIED] **Auction type:** **blind** (members cannot see other bids, before or after clearing; Art. 17-3) **single-price auction**. Supply and demand curves are built per product; their intersection sets the clearing price. If the curves cross at several points, the lowest price is used (Art. 18). Source: 取引規程 Art. 17–18. JEPX outline page: https://www.jepx.jp/electricpower/outline/
- [VERIFIED] **Tick / lot:** bids are priced per 1 kWh, with a **tick of 0.01 JPY/kWh**. Trading and delivery unit is **50 kWh** (per 30-min product). Source: 取引規程 Art. 15.
- [VERIFIED] **Block bids** (several consecutive products bid together) are allowed with prior application. A sell block clears only if the volume-weighted clearing price over its slots is at or above the block price. Source: 取引規程 Art. 17-2, Art. 18-5/6.
- [VERIFIED] **System price vs area price:** the **system price** is the clearing price without market splitting. If the cleared inter-area flows exceed the free interconnector capacity notified by OCCTO, JEPX re-clears each area with the interconnector limits as constraints (市場分断処理). This produces separate **area prices** for the 9 areas (Hokkaido … Kyushu; Okinawa is not connected). Source: 取引規程 Art. 18-4 and the definitions article ("市場分断処理を行わない場合の約定価格…システムプライス").
- [VERIFIED] **Price floor in practice:** the lowest price ever cleared is **0.01 JPY/kWh**, which is one tick. It is reached routinely in Kyushu in spring and occasionally in Tokyo (see 1.4). Source: JEPX spot CSV (see data note).
- [ESTIMATE] **Bid price cap:** I did not find a hard upper bid limit in 取引規程. The highest prices on record are **251.00 JPY/kWh** (system price) and **252.00 JPY/kWh** (Tokyo area price), both on 2021-01-15. Basis: JEPX data. Recommendation: in simulators, cap bids at 999.99 JPY/kWh as a technical limit and treat about 250 JPY/kWh as the historical ceiling. Secondary sources give conflicting cap figures (some say 200, some 999), so this is unverified.
- [VERIFIED] **Scale:** FY2025 spot volume was **284,875 GWh**, and total JEPX volume **291,678 GWh**. FY2024: 265,783 GWh spot. JEPX had **367 trading members** at 2026-03-31 (+46 year on year). JEPX says exchange volume is now "over 30%" of Japan's electricity demand. Source: JEPX FY2025 Business Report (事業報告書). https://www.jepx.jp/company/overview/pdf/BR2025.pdf

> **Data note.** Items marked "(computed)" below were computed by this analyst from JEPX's official 30-minute spot result files (`spot_summary_<FY>.csv`, from https://www.jepx.jp/electricpower/market-data/spot/, downloaded 2026-09-26). Averages are simple means of 30-minute slots. They match JEPX's published FY averages to within ±0.03 JPY/kWh (for example FY2023: 10.74 computed vs 10.74 official). FY2026 covers delivery 2026-04-01 to 2026-09-27 only.

### 1.2 Annual averages (JPY/kWh, fiscal year Apr–Mar)

- [VERIFIED] **System price, JEPX official annual average:** FY2019 **7.93** · FY2020 **11.20** · FY2021 **13.45** · FY2022 **20.38** · FY2023 **10.74** · FY2024 **12.31** · FY2025 **11.08**. Source: JEPX FY2024 and FY2025 Business Reports. https://www.jepx.jp/company/overview/pdf/BR2024.pdf , https://www.jepx.jp/company/overview/pdf/BR2025.pdf
- [VERIFIED] (computed) **Tokyo area price, annual simple mean:** FY2020 **12.02** · FY2021 **14.27** · FY2022 **23.50** · FY2023 **12.20** · FY2024 **13.66** · FY2025 **12.45** · FY2026 to date (Apr 1–Sep 27) **20.36**. Source: JEPX spot CSV.
- [VERIFIED] (computed) **Other areas, FY2025 mean:** Kyushu **9.81**, Kansai **10.65**, Hokkaido **11.70**. FY2024: Kyushu 10.86, Kansai 11.70, Hokkaido 12.64. Source: JEPX spot CSV.
- [VERIFIED] (computed) **FY2026 to date (Apr 1–Sep 27), system price mean:** **16.61**. Kyushu 12.71, Kansai 15.61, Hokkaido 14.14. Source: JEPX spot CSV.
- [VERIFIED] (computed) **Tokyo premium over the system price:** Tokyo differs from the system price in about **90%** of slots (FY2024 89.6%, FY2025 90.0%, FY2026 to date 96.6%). The mean premium is **+1.37** (FY2024), **+1.40** (FY2025) and **+3.75 JPY/kWh** (FY2026 to date). Tokyo minus Kyushu averages +2.64 (FY2025) and +7.66 JPY/kWh (FY2026 to date). Source: JEPX spot CSV.

### 1.3 Monthly and seasonal pattern (Tokyo area)

- [VERIFIED] (computed) **Tokyo monthly means, FY2025 (JPY/kWh):** Apr 11.5, May 11.2, Jun 13.0, Jul 13.9, Aug 13.2, Sep 12.9, Oct 13.1, Nov 11.8, Dec 11.2, Jan 12.1, Feb 11.2, Mar 14.4. Source: JEPX spot CSV.
- [VERIFIED] (computed) **Tokyo monthly means, FY2026 (JPY/kWh):** Apr 20.1, May 18.0, Jun 20.0, Jul 19.9, Aug 21.2, Sep 23.4 (through Sep 27). System price: Apr 14.8, May 14.1, Jun 15.1, Jul 17.9, Aug 19.1, Sep 18.9. Source: JEPX spot CSV.
- [VERIFIED] (computed) **Weekday vs weekend, Tokyo:** FY2025 weekday **13.03** vs weekend **11.00**. FY2024: 14.21 vs 12.28. Source: JEPX spot CSV.

### 1.4 Intraday shape (hour-of-day, mean of the two 30-min slots, JPY/kWh)

- [VERIFIED] (computed) **Tokyo, FY2025, spring (Mar–May), hours 00–23:** 12.5 12.3 12.3 12.5 12.7 12.9 12.8 11.8 11.0 10.8 9.5 8.8 **8.1** 9.4 10.4 11.8 13.6 15.0 **16.0** 15.6 14.9 14.3 14.1 13.2. The trough is at 12:00–13:00 (solar dip). The peak is at 18:00–19:00 (evening ramp). Source: JEPX spot CSV.
- [VERIFIED] (computed) **Tokyo, FY2025, summer (Jun–Sep):** 11.7 11.3 11.2 11.2 11.2 11.1 10.8 10.7 10.7 11.7 11.5 11.9 11.3 13.7 14.9 16.0 18.3 **18.5** 18.3 17.1 15.6 13.9 13.4 12.2. The peak is at 17:00–18:00. Source: JEPX spot CSV.
- [VERIFIED] (computed) **Tokyo, FY2025, winter (Dec–Feb):** 10.5 10.4 10.4 10.3 10.4 10.7 12.4 13.9 12.9 11.5 10.2 9.3 **8.8** 9.3 9.8 11.0 13.3 **14.2** 14.0 13.5 13.3 12.6 11.9 11.0. There is a morning bump at 07:00–08:00, a midday dip, and an evening peak. Source: JEPX spot CSV.
- [VERIFIED] (computed) **Kyushu, FY2025, spring:** 9.6 9.3 10.0 11.0 11.3 11.4 11.1 8.6 6.6 5.1 3.9 2.9 **2.1** 3.0 3.9 5.6 8.2 11.6 **13.9** 13.5 13.0 12.3 11.6 10.1. This is a deep solar "duck curve". Source: JEPX spot CSV.
- [VERIFIED] (computed) **Tokyo, FY2026 to date, spring (Apr–May):** trough **11.8** at 12:00–13:00 and peak **29.7** at 18:00–19:00. Summer (Jun–Sep 27): trough about 17.2 at 06:00–07:00 and peak **27.9** at 18:00–19:00. Source: JEPX spot CSV.
- [VERIFIED] (computed) **0.01 JPY/kWh floor frequency:** Kyushu hit the floor in **983 of 17,520 slots (5.6%)** in FY2025. By month: Mar 195, Apr 252, May 229, Jun 89, Nov 86, Feb 68, Oct 31, Jan 23, Dec 10. Tokyo hit it in **105 slots** (Feb 1, Mar 33, Apr 35, May 36). In FY2026 to date, Kyushu hit it in **771 slots** (425 in May) and Tokyo in **98** (Apr 28, May 70). System price at 0.01: 269 slots (FY2025). Source: JEPX spot CSV.

### 1.5 Volatility (Tokyo area price)

- [VERIFIED] (computed) **FY2025 slot-price distribution:** p5 **7.96**, median **11.53**, p95 **19.43**, max **45.01** (2026-01-26, 16:30–17:00), min 0.01 JPY/kWh. FY2024: p5 8.50 / median 13.14 / p95 20.78 / max 49.65 (2024-09-19). Source: JEPX spot CSV.
- [VERIFIED] (computed) **Daily statistics, FY2025:** the standard deviation of daily means across the year is **2.31**. Mean intraday (max−min) range is **9.45** (median 8.26). The mean within-day standard deviation is **2.66 JPY/kWh**. FY2026 to date: range **22.03** mean, within-day SD 5.63. FY2022 (fuel crisis): mean range 25.12, within-day SD 7.33. Source: JEPX spot CSV.
- [VERIFIED] (computed) **Persistence:** the standard deviation of day-over-day log returns of the Tokyo daily mean is **0.145** (FY2025), 0.159 (FY2024) and 0.169 (FY2026 to date). Slot-to-slot lag-1 autocorrelation is **0.94**. Lag-48 (same slot the next day) autocorrelation is **0.66** (FY2025). Source: JEPX spot CSV.
- [VERIFIED] (computed) **Price vs net load (OLS on 30-min data):** net load is TEPCO area demand minus area solar output.
  - FY2025: Tokyo price ≈ **2.04 + 0.357 × net load (GW)**, r = 0.66. Net load mean 29.2 GW, range 7.3–53.1 GW.
  - FY2026 Apr–Aug: price ≈ 1.23 + **0.699** × net load (GW), r = 0.64. The slope roughly doubled with the fuel shock.

  Sources: JEPX spot CSV joined with TEPCO PG `eria_jukyu` CSVs (section 7).

### 1.6 Notable price events

- [VERIFIED] **Winter 2020/21 crisis:** the system price reached a record **251.00 JPY/kWh on 2021-01-15, slot 16:30–17:00**. The record 48-slot daily mean was **154.6 JPY/kWh on 2021-01-13**. Source: METI/EGC, "スポット市場価格の動向等について" (2021-02-17). https://www.meti.go.jp/shingikai/enecho/denryoku_gas/denryoku_gas/pdf/030_07_00.pdf ; EGC report on the FY2020 winter price spike: https://www.egc.meti.go.jp/activity/emsc_system/pdf/2021061401_haifu.pdf
- [VERIFIED] (computed) In the same event, the **Tokyo area** price peaked at **252.00 JPY/kWh** (2021-01-15 16:30–17:00), with a daily mean of **167.0** on 2021-01-13. Tokyo had **381 slots at or above 100 JPY/kWh** in FY2020. Source: JEPX spot CSV.
- [VERIFIED] (computed) **March 2022 supply-shortage warning (需給ひっ迫警報):** Tokyo prices sat at the **80 JPY/kWh** level. Daily means were 71.9 (2022-03-18), 69.4 (2022-03-22) and **76.7 (2022-03-23)**. Source: JEPX spot CSV.
- [VERIFIED] (computed) **FY2022 fuel crisis:** FY2022 is the record year, with a system price average of 20.38 and a Tokyo average of 23.50. Tokyo hit **200.00 JPY/kWh on 2022-06-29 (16:00–16:30)**, during the June 2022 heat and supply-shortage advisory (需給ひっ迫注意報). Tokyo daily means reached 69.1 (06-29), 74.2 (07-01) and **86.1 (2022-08-03)**. Tokyo had 47 slots at or above 100 JPY/kWh in FY2022. Source: JEPX spot CSV.
- [VERIFIED] (computed) **FY2023–FY2025 were calm:** the Tokyo annual maximum was 50.00 (2023-09-20), 49.65 (2024-09-19) and 45.01 (2026-01-26). There were no slots at or above 50 JPY/kWh in FY2024 or FY2025. Source: JEPX spot CSV.
- [VERIFIED] **April 2026 onward, rise driven by the Middle East:** EGC (制度設計・監視専門会合 No. 21, 2026-06-19, 資料3) gives these causes:
  - fuel costs inside sellers' marginal costs rose by about **10–15 JPY/kWh** due to the Middle East situation;
  - large players' long-term bilateral PPAs **ended at the end of March 2026**, sending large volumes of sell and buy bids to the spot market;
  - Tohoku–Tokyo interconnector capacity was restricted;
  - supply was reduced by plant inspections and outages.

  EGC found no manipulative trading. Tokyo area price maxima rose to the **40–50 JPY/kWh range** in April, eased to the 20s–30s in May, and returned to 40–50 from mid-May. Source: https://www.egc.meti.go.jp/activity/emsc_systemsurveillance/pdf/021_03_00.pdf (index: https://www.egc.meti.go.jp/activity/emsc_systemsurveillance/021_haifu.html)
- [VERIFIED] (secondary) The expired contract is reported to be the **TEPCO EP–JERA** long-term contract (ended 2026-03-31). Background events: a US/Israel strike on Iran in Feb 2026 and Strait of Hormuz shipping risk. JKM LNG rose from about $16 to about $22/MMBtu (late June to early July 2026), and USD/JPY was around 160. Sources: https://jepsolution.jp/2026/06/22/spot_up/ ; https://energy-trend.net/jepx/20260jepx/ ; Cabinet Office monthly topic: https://www5.cao.go.jp/keizai3/monthly_topics/2026/0327/topics_082.pdf
- [VERIFIED] (computed) **FY2026 to date:** Tokyo maximum **64.28 JPY/kWh** (2026-04-28, 18:30–19:00). There were 57 Tokyo slots at or above 50 JPY/kWh. The highest Tokyo daily mean was **31.3** (2026-09-24). Source: JEPX spot CSV.

## 2. JEPX intraday market (時間前市場)

- [VERIFIED] **Mechanism:** continuous trading (ザラ場) in 30-minute products. Trading for each product **opens at 17:00 the day before delivery** and **closes 1 hour before the start of delivery** (gate closure). Tick is 0.01 JPY/kWh and the lot is 50 kWh. Bids name an area. Sources: 取引規程 Art. 63, 66–67 (https://www.jepx.jp/electricpower/outline/pdf/tr_rules.pdf); https://www.jepx.jp/electricpower/outline/
- [VERIFIED] **Volume:** **6,802 GWh** in FY2025 (7,389 GWh in FY2024, 6,168 GWh in FY2023). That is about 2.4% of spot volume. Source: JEPX FY2025 Business Report.
- [VERIFIED] (computed) **Spread vs spot, FY2025:** the national intraday slot average price has a mean of **11.74** vs the system price mean of 11.06, so intraday runs **+0.68 JPY/kWh above the system price**. The standard deviation of that difference is 1.71 and the mean absolute difference 1.25. Against the Tokyo area price the difference is −0.71 (SD 1.92). The mean high–low range of trades within a slot is **8.80 JPY/kWh** (median 6.92). Averages per slot: about **388 MWh** and **176 trades**. Source: JEPX intraday CSV (`intraday_<FY>.csv`, https://www.jepx.jp/electricpower/market-data/intraday/). Note: intraday data are published as national, not by area.
- [VERIFIED] (computed) **FY2024:** premium over the system price +0.74, SD 1.88, in-slot range 8.95, 422 MWh/slot. **FY2026 to date:** premium +1.07, SD 4.63, in-slot range **20.0**, 579 MWh/slot. Source: JEPX intraday CSV.
- [VERIFIED] **System migration:** the new intraday system went live **2026-09-30** for trading of **deliveries from 2026-10-01**. The legacy intraday system trades deliveries up to 2026-09-30 and stays up for data retrieval until 2026-10-09. Source: JEPX notice "取引システムの更改について" (2026-09-08). https://www.jepx.jp/electricpower/news/pdf/jepx20260908.pdf
- [VERIFIED] **Intraday information by area** is to be published with the new JEPX system, and JEPX is studying an intraday auction. Sources: EGC 第8回制度設計・監視専門会合 資料4-1 (2025-04-25) https://www.egc.meti.go.jp/activity/emsc_systemsurveillance/pdf/008_04_01.pdf ; JEPX FY2025 Business Report.

## 3. Imbalance settlement (インバランス料金)

- [VERIFIED] **計画値同時同量 (plan-based balancing, since April 2016):** generation and demand balancing groups (BGs) submit 30-minute plans to OCCTO: day-ahead plans by **12:00 the day before**, with revisions allowed until gate closure (1 hour before delivery). Deviations are settled at the imbalance price. Deliberate, excessive, or inappropriate planning that creates imbalance (意図的なインバランス) is treated as improper conduct. Source (secondary summary): https://energy-advisor.jp/imb/ ; guideline context: 適正な電力取引についての指針 (2026-03-13 edition) https://www.jftc.go.jp/hourei_files/denki.pdf
- [VERIFIED] **April 2022 reform, base price:** the imbalance price equals the **marginal kWh price of the balancing resources dispatched across areas** (広域運用調整力の限界的なkWh価格). When the system is short this is the highest dispatched up-regulation price; when long, the lowest down-regulation price. Prices from each dispatch interval (15 min, later 5 min) are weighted by imbalance volume to give one 30-minute price. If the areas are split, the price is set per split area. Source: EGC/METI "2022年度以降のインバランス料金制度について（中間とりまとめ）" (2019-12-17). https://www.meti.go.jp/shingikai/enecho/denryoku_gas/denryoku_gas/pdf/022_07_02.pdf
- [VERIFIED] **Wholesale-price correction:** if the balancing kWh price and the wholesale price P are inverted, the system-short price is the higher of the two and the system-long price the lower. P is the simple average of the **last five intraday trades from five different participants**, falling back to the area price. When solar or wind is being curtailed and the system is long, the imbalance price is **0 JPY/kWh**. Source: same 中間とりまとめ.
- [VERIFIED] **Scarcity-adjusted imbalance price (需給ひっ迫時補正インバランス料金):** this is a piecewise-linear function of an index. The index is (wide-area supply − wide-area demand) / demand at gate closure, and from FY2024 it is the **広域予備率 (wide-area reserve margin)**. The final price is the higher of this and the base price. Parameters:
  - **B = 10%**: the curve starts rising, based on when 電源Ⅰ' is typically called.
  - **B' = 8%**: the price reaches **D**, based on OCCTO's tightness criterion.
  - **A = 3%**: the price reaches the cap **C**, based on the supply-shortage warning threshold.
  - **C**: 600 JPY/kWh in principle; **200 JPY/kWh** provisionally for FY2022–FY2023.
  - **D = 45 JPY/kWh**.

  Source: same 中間とりまとめ (p.4–6).
- [VERIFIED] **C and D by fiscal year:**
  - FY2022–FY2023: C **200**, D **45** JPY/kWh.
  - FY2024–FY2025 and until 2026-09-30: C held at **200**, D at **45** (the planned move to 600 was dropped).
  - From **2026-10-01**: C **300**, D **50** JPY/kWh "for the time being". This was originally planned for April 2026 and was moved to October because JEPX's intraday system change was delayed.

  Basis for 300: the 3-year average capacity-market price (253) plus D (45) is about 300. Sources: EGC 第8回制度設計・監視専門会合 資料4-1 (2025-04-25) https://www.egc.meti.go.jp/activity/emsc_systemsurveillance/pdf/008_04_01.pdf ; https://energy-advisor.jp/imb-price2-2/ ; https://note.com/enechain_biz/n/n9a84d4a25737 ; https://nagasawa-associates.com/insights/global-macro/notes/japan-imbalance-price-cap
- [VERIFIED] **Cumulative price threshold (累積価格閾値制度, new with the 300 cap):** if the **spot area price is at or above 200 JPY/kWh for 30 cumulative slots within the previous 7 days**, the scarcity imbalance cap drops to **100 JPY/kWh** from the next day. It is released once there are zero slots at or above 100 JPY/kWh in the previous 7 days. Source: EGC 008_04_01.
- [ESTIMATE] **Curve shape between points:** linear from 0 at 10% to D at 8%, then linear from D at 8% to C at 3%, flat at C below 3%. Basis: the linear-formula description in the 中間とりまとめ (「直線的な式」). The exact value at B was not restated in the text I could read.
- [VERIFIED] (computed) **Observed Tokyo imbalance prices:** in all slots checked, the surplus and shortage prices were identical (single price).
  - FY2025: mean **11.75** vs Tokyo spot 12.43. Imbalance minus spot has mean −0.68, SD **4.93**, p5 −7.67, p95 +5.72. 38 slots were at or above 45 JPY/kWh and 8 at or above 100. Max 131.49 (2025-09-08 16:30–17:00). **694 slots at 0.00**.
  - FY2024: mean 13.92, difference SD 7.03, max **194.11** (2024-07-08 09:00–09:30).
  - FY2026 to date: mean 17.85, difference SD 9.42, and one slot at **200.00** (2026-07-22 16:30–17:00).

  Source: Imbalance Price Central Calculation System (インバランス単価中央算定システム) monthly CSVs, https://www.imbalanceprices-cs.jp/ (`public/price/YYYY/MM/YYYYMM_imbalance-price_01.csv`).

## 4. 2026 market-structure changes

### 4.1 JEPX trading-system replacement (in-house, API-only)

- [VERIFIED] **Timeline:**
  - Dec 2024: dedicated-line connection spec published.
  - Feb 2025: spot matching engine switched.
  - Mar 2025: day-ahead API spec published.
  - May 2025: intraday API spec published.
  - Oct 2025: spot test environment opened.
  - Dec 2025: intraday test environment opened.
  - **2026-03-25**: new spot system went live (for delivery from 2026-04-01).

  Sources: JEPX FY2024 and FY2025 Business Reports (BR2024.pdf, BR2025.pdf).
- [VERIFIED] **No GUI:** the new system provides functions through **server-to-server data communication over dedicated lines**, and "no screens are provided" (画面の提供はございません). Non-members may build and operate connecting systems. Source: JEPX notice 2025-04-10. https://www.jepx.jp/system/news/pdf/jepx20250410.pdf
- [VERIFIED] **Legacy sunset:** the legacy **spot** system runs in parallel only for deliveries up to **2027-03-31**. By then members must build their own system or contract a JEPX-listed connection vendor. The legacy **settlement** system is also retired after 2027-03-31. The **intraday** market moves to the new system for delivery from **2026-10-01**. Baseload, FTR and forward markets get a new screen (no API) by March 2027. Source: JEPX notice 2026-09-08. https://www.jepx.jp/electricpower/news/pdf/jepx20260908.pdf

### 4.2 Balancing market (需給調整市場, operated by EPRX)

- [VERIFIED] **Products:** all have a 30-minute bid unit, 1 MW minimum bid, 1 kW step, and only upward (上げ) capacity is procured at present.

  | Product | English name | Response | Duration | Signal |
  |---|---|---|---|---|
  | 一次 | FCR | ≤10 s | ≥5 min | offline / governor |
  | 二次① | S-FRR | ≤5 min | 30 min | LFC |
  | 二次② | FRR | ≤5 min | 30 min | EDC |
  | 三次① | RR | ≤15 min | 30 min | EDC |
  | 三次② | RR-FIT | ≤60 min | 30 min | online |

  Source: EPRX "需給調整市場の商品要件と取引スケジュール" 第6版 (2026-03-13). https://www.eprx.or.jp/outline/docs/shouhin_ver.6_20260313.pdf
- [VERIFIED] **FY2026 reform:** the weekly products (一次–三次①, the "複合市場") moved to **day-ahead trading in 30-minute units from 2026-03-14**. Deduction of 自然体余力 ended on 2026-03-13. Bids for both the combined market and 三次② are accepted **11:30–14:00 the day before**, with clearing by **15:00**. The window opening moved 30 minutes earlier. Sources: EGC 第21回制度設計・監視専門会合 資料6 (2026-06-19) https://www.egc.meti.go.jp/activity/emsc_systemsurveillance/pdf/021_06_00.pdf ; EPRX 商品要件 第6版.
- [VERIFIED] **Combined-market price cap:** **15 JPY/ΔkW·30min** for deliveries from 2026-03-14. Source: EGC 021_06_00.
- [VERIFIED] **Sequencing:** ANRE (Oct 2025) planned the move of weekly products to day-ahead for April 2026. EGC shows it took effect on 2026-03-14. Under the fair-trading guideline, sellers are expected to offer all surplus to spot at 10:00 the day before, so only unsold capacity reaches the balancing market at 14:00. Sellers cannot yet offer the same capacity to both the combined market and 三次②. Source: ANRE 資料4 (2025-10-29). https://www.meti.go.jp/shingikai/enecho/denryoku_gas/jisedai_kiban/system_review/pdf/108_04_00.pdf
- [VERIFIED] **Procurement cost:** market procurement cost across all areas was **23.6 bn JPY** in April 2024 (weekly 10.0 + day-ahead 13.6). It fell to about **12.4–16.7 bn JPY/month** from late 2024 to September 2025, after cuts to 三次② procurement volumes (from June 2024) and deduction of out-of-market balancing (from June 2025). Source: ANRE 108_04_00.
- [VERIFIED] **FY2024 average procurement prices (JPY/ΔkW·h):**
  - Weekly/combined: Hokkaido 10.31, Tohoku 5.67, **Tokyo 4.18**, Chubu 5.30, Kansai 5.81, Kyushu 8.66.
  - 三次② (day-ahead): Hokkaido 9.60, **Tokyo 11.51**, Chubu 10.65, Kansai 3.61, Kyushu 2.81.
  - Tokyo combined monthly range in FY2024: 2.3–7.9.

  Source: ANRE 108_04_00, p.6–7.
- [VERIFIED] **By resource type (JPY/ΔkW·h):**

  | Market | Period | Thermal | Pumped/hydro | Battery | VPP/DR | All |
  |---|---|---|---|---|---|---|
  | Combined | FY2024 | 5.99 | 4.14 | 31.39 | 14.42 | 5.77 |
  | Combined | FY2025 Apr–Sep | 5.93 | 4.47 | 22.93 | 36.82 | 6.00 |
  | 三次② | FY2024 | 11.78 | 1.53 | **330.07** | 110.92 | 6.64 |
  | 三次② | FY2025 Apr–Sep | 2.91 | 1.43 | 58.65 | 120.40 | 2.30 |

  Source: ANRE 108_04_00, p.9.
- [VERIFIED] **三次② after the reform, 2026 (JPY/ΔkW·30min):**
  - Average cleared price, Tokyo: Apr **3.80**, May **12.20**, Jun 1–10 4.66. Other areas in May: Hokkaido 4.26, Chubu 3.98, Kansai 1.70, Kyushu 2.26.
  - Maximum cleared price: 200.00 in several areas in April, then 75–138 in May. Minimum about 0.29–0.39.
  - Tokyo's estimated cost rose from 0.906 bn JPY (Apr) to 1.74 bn JPY (May). EGC questioned high-price bidders about how they calculate their fixed-cost recovery adder.

  Source: EGC 021_06_00, p.3–4.
- [VERIFIED] **Combined (一次–三次①) market after the reform, 2026 (JPY/ΔkW·30min):**
  - Average cleared price, Tokyo: Apr **2.68**, May **2.57**, Jun 2.39. Range across areas 0.87–4.95.
  - Maximum cleared price about 15–23.6 (15 cap; settlement is capped at 15).
  - Tokyo cleared volume: 1,795,718 ΔMW (Apr) and 1,579,415 ΔMW (May). Cost 4.82 bn and 4.06 bn JPY.
  - Primary reserve (一次) is still under-procured in many areas.

  Source: EGC 021_06_00, p.7, 10.
- [VERIFIED] **B-type resources:** these are resources recovering fixed costs through the ΔkW price. In FY2025 there were **37 cases from 9 companies**: 28 generators, **4 batteries, 5 battery-VPPs**. Recovery rates were about 1–88% of the allowed fixed-cost cap. Source: EGC 021_06_00, p.17.
- [VERIFIED] **EPRX trading fee:** **0.03 JPY/ΔkW·30min** (excl. tax) in FY2025. The FY2024 fee was 0.01 JPY/ΔkW·30min, which equals 0.02 JPY/ΔkW·h. Source: EPRX notice (2025-02-07). https://www.eprx.or.jp/j_information/2025/02/07_1655.php

## 5. Retail cost stack for high-voltage (高圧) and extra-high-voltage (特別高圧) C&I customers, TEPCO PG area

> All TEPCO tariff figures are tax-inclusive unless noted. TEPCO PG rate documents are listed at https://www.tepco.co.jp/pg/consignment/notification/index-j.html (versions effective 2024-04-01, 2024-10-01, 2025-04-01, 2026-04-01, 2026-10-01, 2026-11-01).

### 5.1 Wheeling charges (託送料金, revenue-cap regime from April 2023)
- [VERIFIED] **April 2024 revision (generation-side charge introduced):** the energy charge was cut for **高圧標準 from 2.37 to 1.84 JPY/kWh** and for **特高標準 from 1.33 to 0.91 JPY/kWh**. Basic charges were unchanged. Source: TEPCO PG filing. https://www.tepco.co.jp/pg/consignment/notification/pdf/shinsei20231201.pdf
- [VERIFIED] **April 2024 to October 2026, standard contracts:**
  - **高圧標準** (6 kV, generally 50–2,000 kW): **653.87 JPY/kW-month + 1.84 JPY/kWh**.
  - **特別高圧標準** (2,000 kW or more; 20/60/140 kV): **423.39 JPY/kW-month + 0.91 JPY/kWh**.

  Sources: https://www.tepco.co.jp/pg/consignment/notification/pdf/takusou_yakkan20260213.pdf ; https://www.tepco.co.jp/pg/consignment/notification/pdf/takusou_yakkan20260722.pdf
- [VERIFIED] **Time-of-use options (2026-04 約款):**
  - 高圧時間帯別: 653.87 JPY/kW-month; day 1.93 JPY/kWh, night 1.75 JPY/kWh.
  - 特高時間帯別: 423.39 JPY/kW-month; day 0.94 JPY/kWh, night 0.89 JPY/kWh.
  - Power-factor adjustment: ±1% of the basic charge for each 1% the power factor is above or below 85%.

  Source: takusou_yakkan20260213.pdf.
- [VERIFIED] **From 2026-11-01:** 高圧標準 **762.44 JPY/kW-month** (+16.6%) + 1.84 JPY/kWh. 特高標準 **446.25 JPY/kW-month** + 0.91 JPY/kWh. This follows METI's approval on **2026-09-04** of a revenue cap raised to 7.6062 trillion JPY for FY2023–27 (+251.6 bn JPY). PG average unit price, excluding tax: 高圧 3.78 → 4.13 JPY/kWh; 特高 2.05 → 2.11 JPY/kWh. Sources: https://www.tepco.co.jp/pg/consignment/notification/pdf/takusou_yakkan20260911.pdf ; https://www.tepco.co.jp/pg/company/press-information/press/2026/pdf/26x4101.pdf
- [VERIFIED] **Generator-side charge (発電側課金):** **87.01 JPY/kW-month + 0.28 JPY/kWh** from April 2024 to October 2026. From November 2026: 100.12 JPY/kW-month + 0.32 JPY/kWh. Locational discounts apply. Sources: shinsei20231201.pdf ; takusou_yakkan20260911.pdf.
- [ESTIMATE] **All-in wheeling per kWh for a 1 MW 高圧 factory at 60% load factor** (about 438 MWh/month): basic charge 653.87 × 1,000 ÷ 438,000 = 1.49 JPY/kWh. Adding the energy charge of 1.84 gives about **3.3 JPY/kWh**. From November 2026 it rises to about **3.6 JPY/kWh**. Basis: tariff arithmetic, ignoring power-factor adjustment.

### 5.2 Capacity contribution (容量拠出金)
- [VERIFIED] **Main auction clearing prices by delivery year (Tokyo area):**

  | Delivery year | Tokyo price (JPY/kW-yr) | National total |
  |---|---|---|
  | FY2024 | **14,137** (uniform nationally) | 1兆5,987億円 |
  | FY2025 | **3,495** | 5,140億円 |
  | FY2026 | **5,834** | 8,504億円 |
  | FY2027 | **9,555** | 1兆3,140億円 |
  | FY2028 | **14,812** | 1兆8,506億円 |
  | FY2029 | **15,111** (results 2026-01-20) | 2兆2,094億円 |

  Net CONE was about 9,400–10,100 JPY/kW over this period. Sources: OCCTO result PDFs:
  - FY2024: https://www.occto.or.jp/assets/market-board/market/oshirase/2020/files/200914_mainauction_youryouyakujokekka_kouhyou_jitsujukyu2024.pdf
  - FY2025: https://www.occto.or.jp/assets/market-board/market/oshirase/2021/files/220119_mainauction_keiyakukekka_saikouhyou_jitsujukyu2025.pdf
  - FY2026: https://www.occto.or.jp/assets/market-board/market/oshirase/2022/files/230222_mainauction_youryouyakujokekka_saikouhyou_jitsujukyu2026.pdf
  - FY2027: https://www.occto.or.jp/assets/market-board/market/oshirase/2023/files/240124_mainauction_youryouyakujokekka_kouhyou_jitsujukyu2027.pdf
  - FY2028: https://www.occto.or.jp/assets/market-board/market/oshirase/2024/files/250129_mainauction_youryouyakujokekka_kouhyou_jitsujukyu2028.pdf
  - FY2029: https://www.occto.or.jp/assets/iinkai/youryou_kentoukai/71/youryou_kentoukai_71_03.pdf
- [VERIFIED] **Tokyo-area retailers' burden:**
  - FY2024: **492.18 bn JPY**.
  - FY2025: 140.69 bn JPY at the main auction, then **134.30 bn JPY** after the additional auction.
  - FY2026: 245.99 bn JPY at the main auction, then **252.83 bn JPY** after the July 2025 additional auction (which cleared at 8,749 JPY/kW in Tokyo).

  Sources: OCCTO main and additional auction result PDFs (above), plus https://www.occto.or.jp/assets/market-board/market/oshirase/2025/files/250728_tsuikaauction_youryouyakujokekka_kouhyou_jitsujukyu2026.pdf
- [ESTIMATE] **Per-kWh equivalent, Tokyo area:** FY2024 about **1.84**, FY2025 about **0.50**, FY2026 about **0.94 JPY/kWh**. National figures: about 1.90 / 0.59 / 1.04. Basis: Tokyo retailers' burden ÷ Tokyo area demand of about 267–268 TWh. For FY2028–FY2029, about 14,800–15,100 JPY/kW implies roughly 2.5–2.7 JPY/kWh (Tokyo retailer burden of about 711.5 bn JPY in FY2028, secondary source https://pps-net.org/capacity-market/kanto).
- [VERIFIED] TEPCO EP does **not** show a separate capacity-contribution line in its 高圧/特高 standard tariffs; it is embedded in the basic and energy charges. Source: https://www.tepco.co.jp/ep/corporate/plan_h/pdf/2026minaoshisiryou.pdf

### 5.3 Renewable energy surcharge (再エネ賦課金)
- [VERIFIED] **FY2023: 1.40 JPY/kWh.** Source: TEPCO HD fact table. https://www.tepco.co.jp/corporateinfo/illustrated/charge/1253678_6290.html
- [VERIFIED] **FY2024: 3.49 JPY/kWh** (bills May 2024–Apr 2025). Source: METI. https://www.meti.go.jp/press/2023/03/20240319003/20240319003.html
- [VERIFIED] **FY2025: 3.98 JPY/kWh** (bills May 2025–Apr 2026). Source: METI. https://www.meti.go.jp/press/2024/03/20250321006/20250321006.html
- [VERIFIED] **FY2026: 4.18 JPY/kWh** (bills May 2026–Apr 2027, announced 2026-03-19). METI assumed purchase costs of 4.8507 trillion JPY, avoided costs of 1.6495 trillion JPY, and sales of 766.5 TWh. Source: METI. https://www.meti.go.jp/press/2025/03/20260319004/20260319004.html

### 5.4 Market-linked (市場連動型) and standard C&I tariffs, TEPCO EP
- [VERIFIED] **Market-price adjustment (市場価格調整):** introduced in April 2023. It passed about 30% of JEPX movements into the legacy menus. Source: https://www.tepco.co.jp/ep/notice/pressrelease/2023/1666212_8668.html
- [VERIFIED] **Three standard 高圧/特高 plans since FY2024:**
  - **ベーシックプラン:** fuel adjustment plus spot adjustment in 4 time bands.
  - **市場調整ゼロプラン:** fuel adjustment only.
  - **市場価格連動プラン:** 100% spot-linked.

  Contracts are one year to March 31. Source: https://www.tepco.co.jp/ep/corporate/plan_h/minaoshi_2025plan.html
- [VERIFIED] **Formula:** market adjustment = (average JEPX spot price − base spot price) × 基準市場単価. The bill is basic + energy ± fuel/market adjustments + 再エネ賦課金. Weekday time bands (including Saturday): morning 8–13, midday 13–16, evening 16–22; all other hours are night. Sources: https://www.tepco.co.jp/ep/corporate/adjust2/index-j.html ; https://www.tepco.co.jp/ep/notice/pressrelease/2023/pdf/230927j0201.pdf
- [VERIFIED] **FY2026 parameters (Kanto 高圧):**
  - Base spot price **11.60 JPY/kWh** (FY2025: 12.64).
  - 基準市場単価: market-linked plan **1.142**. ベーシック plan 0.492 (Jul–Sep), 0.474 (Dec–Feb) and 0.397 (other months).
  - ベーシック base fuel price 35,600 JPY/kl.
  - Fuel adjustment now uses a 1-month average (it was 3 months).

  Source: https://www.tepco.co.jp/ep/corporate/plan_h/pdf/2026minaoshisiryou.pdf
- [VERIFIED] **TEPCO EP 高圧 plan prices** (basic JPY/kW-month + energy JPY/kWh, before adjustments):

  | Plan | FY2024 | FY2025 | FY2026 (from 2026-04-01) |
  |---|---|---|---|
  | ベーシック | 1,890 + 19.51 | 3,030 + 16.56 | **2,530 + 17.43** |
  | 市場調整ゼロ | 2,100 + 20.70 | 3,220 + 16.63 | **2,720 + 17.21** |
  | 市場価格連動 | 1,700 + 14.75 | 1,500 + 16.37 | **1,500 + 15.18 (night 15.00)** |

  Sources: https://www.tepco.co.jp/ep/notice/pressrelease/2024/pdf/240206j0102.pdf ; 2026minaoshisiryou.pdf
- [VERIFIED] About **10,000** customers had signed up to the new plans by September 2024. Source: https://www.tepco.co.jp/ep/notice/pressrelease/2024/pdf/24x1302.pdf
- [VERIFIED] **Government subsidy (電気・ガス料金支援) for 高圧,** in JPY/kWh by usage month (特高 excluded):

  | Period | 高圧 subsidy (JPY/kWh) |
  |---|---|
  | Jul / Aug / Sep 2025 | 1.0 / 1.2 / 1.0 |
  | Jan–Feb 2026 / Mar 2026 | 2.3 / 0.8 |
  | Jul / Aug / Sep 2026 | **1.8 / 2.3 / 1.8** |

  Sources: https://www.tepco.co.jp/pg/company/press-information/press/2025/pdf/250611j0101.pdf ; https://www.tepco.co.jp/pg/company/press-information/press/2026/pdf/26x1801.pdf
- [ESTIMATE] **Generic market-linked C&I design used by new entrants:** JEPX Tokyo area price (30-min, often with a loss factor of about 1.03–1.05) plus a fixed service fee of about 1–3 JPY/kWh, plus wheeling pass-through, capacity contribution, 再エネ賦課金 and non-fossil cost. Basis: common industry practice. No single primary source was found, so the adder and loss-factor values are assumptions.

## 6. Non-fossil certificates (非化石証書) and hourly matching

### 6.1 Market design
- [VERIFIED] **Two JEPX markets:**
  - **再エネ価値取引市場** trades FIT certificates. Retailers and end customers can both buy. It was created in November 2021, and FIT certificates have been fully tracked since FY2021.
  - **高度化法義務達成市場** trades non-FIT certificates, split into 再エネ指定 (renewable-designated) and 指定なし (unspecified). Only retailers can buy, except for direct purchases from qualifying plants that started in FY2022 or later. Non-FIT certificates have been **fully tracked (全量トラッキング) from FY2024**.

  Source: ANRE 再エネ小委 資料 (2025-09-30), p.6. https://www.meti.go.jp/shingikai/enecho/denryoku_gas/saisei_kano/pdf/076_01_00.pdf ; JEPX FY2025 Business Report.
- [VERIFIED] **Auction frequency:** 4 auctions per fiscal year, clearing roughly in late August, late November, late February and late May (the May round belongs to the previous fiscal year). Source: JEPX non-fossil results CSV `nf_summary_<FY>.csv`, https://www.jepx.jp/nonfossil/market-data/
- [VERIFIED] **Price bands:** FIT **0.4–4.0 JPY/kWh**; non-FIT **0.6–1.3 JPY/kWh**. Prices "often stick to the floors". Source: ANRE 資料 (2026-03-04), pp.15–19. https://www.meti.go.jp/shingikai/enecho/denryoku_gas/jisedai_kiban/system_review/pdf/112_06_00.pdf
- [VERIFIED] **Phase 3 (FY2026–FY2028) proposals:** bands unchanged in FY2026. The FIT floor rises to **0.6** in FY2027 and later follows the non-FIT floor, and the FIT cap is abolished. The non-FIT floor rises to **0.8** by FY2028, and the non-FIT cap stays at 1.3. Reference: the GX-ETS FY2026 floor of 1,700 JPY/t-CO2 is about 0.66–0.72 JPY/kWh. Source: ANRE 112_06_00.

### 6.2 Recent clearing prices (JPY/kWh) and volumes
- [VERIFIED] **FIT:**

  | Auction (clearing date) | Price (JPY/kWh) | Volume |
  |---|---|---|
  | FY2024 R1 (2024-08-30) | 0.40 | 14.38 TWh |
  | FY2024 R2 (2024-11-29) | 0.40 | 11.65 TWh |
  | FY2024 R3 (2025-02-28) | 0.40 | 15.34 TWh |
  | FY2024 R4 (2025-05-23) | 0.67 | 19.07 TWh |
  | FY2025 R1 (2025-08-29) | 0.40 | 20.98 TWh |
  | FY2025 R2 (2025-11-28) | 0.40 | 15.22 TWh |
  | FY2025 R3 (2026-02-27) | 0.40 | 18.88 TWh |
  | FY2025 R4 (2026-05-22) | **0.44** | 18.00 TWh |
  | FY2026 R1 (2026-08-31) | **0.40** | 23.12 TWh |

  In FY2025 R4, 83.2 TWh was offered for sale and 303 members bid. Source: JEPX nf_summary CSVs (FY2025 file checked directly by this analyst).
- [VERIFIED] **Non-FIT 再エネ指定:**
  - FY2024: 0.60 (R1–R2), then **1.30 (cap)** in R3–R4.
  - FY2025: 0.91 (R1), then **1.30** in R2–R4.
  - FY2026 R1 (2026-08-28): **1.21**.

  Non-FIT 指定なし: FY2025 0.72 (R1), then 1.30. FY2026 R1: 1.20. Buy bids far exceed supply: in FY2025 R4, 1.71 TWh of buy bids against 1.05 TWh cleared for 再エネ指定. Source: JEPX nf_summary CSVs.
- [ESTIMATE] **Full-year FIT totals:** FY2024 **60.4 TWh** at about **0.49 JPY/kWh** volume-weighted. FY2025 **73.1 TWh** at about **0.41 JPY/kWh**. Basis: arithmetic on the JEPX rows.

### 6.3 Granular / hourly certificates
- [VERIFIED] **No government hourly or 30-minute certificate yet.** In September 2025, ANRE listed time and location value (時間的価値・場所的価値) as a longer-term issue, after 2030. Committee members asked for timestamps and 24/7 or RE100 alignment. Source: ANRE 076_01_00, pp.17, 21–22.
- [VERIFIED] **Private pilots** (EnergyTag APAC Factbook, Aug 2025):
  - JERA Group with Granular Energy: hourly renewable data.
  - Flexidao with JERA Cross: hourly matching.
  - 電力シェアリング (D-Sharing): half-hourly matching of community solar to daytime EV charging, an MOE pilot.

  Japan's smart meters give **30-minute** data. Source: https://energytag.org/wp-content/uploads/2025/08/APAC-Factbook-on-Granular-Electricity-Accounting.pdf (pp.22, 30)

### 6.4 Google 24/7 CFE
- [VERIFIED] **Methodology:** Google CFE is the share of Google's electricity use on a regional grid matched **hourly** with carbon-free energy. It is the sum of:
  - **contracted CFE** (Google's own agreements, capped at 100% in any hour), and
  - **consumed grid CFE** (the grid's hourly carbon-free share from Electricity Maps, applied to the rest of the load).

  Excess contracted energy in an hour does not count. The global figure is load-weighted. The goal is 24/7 CFE on every grid by 2030. Source: Google 2026 Environmental Report. https://sustainability.google/files/google-2026-environmental-report
- [VERIFIED] **Global CFE:** **65%** in 2025, 66% in 2024, 64% in 2023. 9 of 22 grid regions were at or above 80%. Asia-Pacific averaged 13%. Electricity use grew 37% in 2025. Source: Google 2026 Environmental Report.
- [VERIFIED] **Japan (TEPCO grid):** Google CFE **23% in 2025** (contracted 7% + consumed grid 16%), with grid CFE 18%. In 2024 it was **17%** (no contracted CFE). The Inzai data center PUE is 1.12. Sources: Google 2026 Environmental Report; Google 2025 Environmental Report https://www.gstatic.com/gumdrop/sustainability/google-2025-environmental-report.pdf
- [VERIFIED] **Google's Japan deals:**
  - Shizen Energy: **20 MWac** solar PPA on the same grid as Inzai (announced 2024-05-24; construction 2026–27). https://www.shizenenergy.net/en/2024/05/24/se_signs_ppa_google/
  - Clean Energy Connect: about 800 small solar sites (same day). https://www.esgtoday.com/google-signs-its-first-renewable-energy-purchase-deals-in-japan/
  - JERA Cross: **15 MWac** solar virtual PPA for Inzai, delivering by March 2027. https://www.jera.co.jp/en/news/information/20250924_2267
  - Kioxia: hydropower retrofit in the Chūbu region, **160 GWh/yr** (Google 2026 Environmental Report).
- [ESTIMATE] The Clean Energy Connect deal was reported at about 40 MW over 20 years. Basis: search snippets only.

## 7. Tokyo-area demand, tightness events and load growth

- [VERIFIED] **All-time TEPCO peak:** **64.30 GW on 2001-07-24** (generation-end basis; the measurement basis changed to area sending-end from FY2016). Source: https://www.tepco.co.jp/corporateinfo/illustrated/power-demand/peak-demand-daily-j.html
- [VERIFIED] **Recent seasonal peaks** (same TEPCO HD table):

  | Fiscal year | Summer peak | Winter peak |
  |---|---|---|
  | FY2021 | — | 53.74 GW (2022-01-06) |
  | FY2022 | **59.30 GW (2022-08-02)** | 51.79 GW (2023-02-10) |
  | FY2023 | 55.25 GW (2023-07-18) | 49.90 GW (2024-02-05) |
  | FY2024 | 56.99 GW (2024-07-29) | 48.37 GW (2025-03-05) |
- [VERIFIED] **FY2025–FY2026:**
  - Summer 2025 peak **57.54 GW** on 2025-08-06 (13–14h; supply 67.42 GW, 85% usage).
  - Winter FY2025 peak 50.29 GW (2026-02-09).
  - Summer 2026 peak so far **56.42 GW** on 2026-07-22 (90% usage).

  Sources: https://www.tepco.co.jp/forecast/html/calendar2025-j.html ; https://www.tepco.co.jp/forecast/html/calendar-j.html
- [VERIFIED] **Annual Tokyo area demand:** **267.5 TWh** (FY2024) and **268.3 TWh** (FY2025). Source: TEPCO HD FY2025 results. https://www.tepco.co.jp/about/ir/library/results/pdf/2603q4gaiyou-j.pdf
- [VERIFIED] **March 2022 需給ひっ迫警報 (the first ever):**
  - Issued 2022-03-21 at 20:00 for Tokyo; Tohoku was added 03-22 at 11:30.
  - Causes: 3.35 GW of plant tripped in the 03-16 earthquake, the Tohoku–Tokyo interconnector was halved to 2.5 GW, and it was cold.
  - Forecast demand 48.4 GW. Conservation saved about 44 GWh.

  Source: METI. https://www.meti.go.jp/shingikai/enecho/denryoku_gas/denryoku_gas/pdf/046_03_01.pdf
- [VERIFIED] **June 2022 需給ひっ迫注意報 (Tokyo):** issued for 2022-06-27, with forecast reserve margins of 4.7% and 3.7%. Tokyo spot hit 200 JPY/kWh on 06-29 (section 1.6). Source: OCCTO. https://www.occto.or.jp/institution/shiji/20220626_jukyushiji.html
- [ESTIMATE] The June 2022 advisory was the first use of the 注意報 level, and the advisory period ran through about 06-30 in a record June heatwave. Basis: secondary reports and recollection; not re-verified in a primary source.
- [VERIFIED] **Summer 2026:** TEPCO PG says it has secured a 3% reserve margin. Source: https://www.tepco.co.jp/pg/company/press-information/information/2026/pdf/260521j0101.pdf
- [VERIFIED] **OCCTO 2026 demand forecast (published 2026-01-21):**
  - National summer peak: **158.8 GW** (FY2025 actual) → **159.6 GW** (FY2026) → **164.6 GW** (FY2035).
  - National energy: **803.4 TWh** (FY2026) → **846.1 TWh** (FY2035).
  - **Data-center and semiconductor additions:** +0.83 GW (FY2026), **+4.20 GW (FY2030)**, **+7.62 GW (FY2035**; data centers 6.61, semiconductors 1.01); +56.8 TWh by FY2035. OCCTO notes data-center timing has slipped compared with the previous forecast.
  - **Tokyo summer peak:** **55.0 GW (FY2026) → 58.9 GW (FY2035)**, +0.8%/yr, the fastest growth together with Hokkaido.

  Source: https://www.occto.or.jp/assets/news/juyousoutei/260121_juyousoutei_r1.pdf
- [VERIFIED] **OCCTO 2025 forecast:** national peak 164.6 GW by FY2034, with data-center and semiconductor additions of **+7.15 GW by FY2034**. Source: https://www.occto.or.jp/assets/juyousoutei/2024/files/250122_juyousoutei.pdf
- [VERIFIED] **7th Strategic Energy Plan (2025-02-18), FY2040:** generation about **1.1–1.2 trillion kWh** (FY2023 actual: 985.4 TWh); demand 0.9–1.1 trillion kWh. Mix: renewables 40–50%, nuclear about 20%, thermal 30–40%. Source: https://www.enecho.meti.go.jp/category/others/basic_plan/pdf/20250218_02.pdf
- [VERIFIED] (computed) **TEPCO PG area, FY2025 (30-min "エリア需給実績"):**
  - Area demand **281.4 TWh**. Maximum 30-min mean demand **57.67 GW** (2025-08-06 13:30). Minimum **18.30 GW**.
  - Supply mix as a share of demand: LNG **47.9%**, coal 17.0%, interconnector imports **14.1%**, solar **9.2%** (25.96 TWh), hydro 3.6%, oil 1.4%, biomass 1.2%, wind 0.4%, nuclear 0.3%.
  - Solar output maximum **17.04 GW** (2026-03-24 11:30). Solar covered up to **68.4%** of area demand in a single slot.
  - Solar curtailment in only 68 slots (0.03 TWh).
  - Grid-battery output recorded as a separate line: max discharge only 45 MW.

  Source: TEPCO PG area supply-demand CSVs `eria_jukyu_YYYYMM_03.csv` (https://www.tepco.co.jp/forecast/html/area_jukyu-j.html).
- [VERIFIED] (computed) **TEPCO PG area, FY2026 Apr–Aug:**
  - Demand **109.5 TWh**, maximum **56.46 GW** (2026-07-22 14:30).
  - Nuclear **4.4%** of demand (4.79 TWh). Nuclear output in the TEPCO area was 0 until January 2026, first appeared in February 2026 (max 1,184 MW), and has run at about **1.29–1.32 GW** since April 2026. This is consistent with **Kashiwazaki-Kariwa Unit 6** restarting; one search-engine excerpt gave commercial operation from 2026-04-16, which is [ESTIMATE] because the ANRE page returned HTTP 403. LNG 43.2%, solar 10.8%.
  - Solar maximum **17.84 GW** (2026-04-08 11:30). Solar curtailment in **249 slots** (0.22 TWh), a sharp rise.

  Source: same CSVs.
- [VERIFIED] (computed) **Hour-of-day profiles, TEPCO area FY2025 (GW, hours 00–23):**
  - Summer (Jul–Aug) demand: 29.9 27.9 26.9 26.6 26.6 27.0 29.0 33.0 38.5 42.7 44.6 45.9 45.9 46.7 46.6 46.2 45.6 43.8 42.6 41.3 39.2 37.0 34.9 32.7.
  - Summer solar: 0 0 0 0 0 0.4 2.0 4.7 7.4 9.7 11.2 12.1 12.0 10.8 8.9 6.4 3.5 1.2 0.1 0 …
  - Winter (Dec–Feb) demand: 30.1 28.9 28.5 28.5 28.9 30.5 33.8 36.9 39.0 39.3 38.1 37.1 35.6 35.7 35.5 35.8 37.1 38.7 39.2 38.8 38.1 36.6 34.6 32.5.
  - Spring (Apr–May) demand: 22.9 21.9 21.9 22.2 22.4 22.5 23.0 24.4 26.7 28.6 29.2 29.5 28.7 29.2 29.1 29.0 29.3 29.4 30.1 29.7 28.6 27.2 25.9 24.5.
  - Spring solar: 0 … 0.3 1.5 3.8 6.2 8.2 9.5 10.1 9.8 8.9 7.2 5.0 2.6 0.7 0 …

  Source: same CSVs.
- [VERIFIED] (computed) **Calendar 2024 (hourly 実績):** TEPCO area demand **281.6 TWh**, peak hourly **56.99 GW** (2024-07-29 14:00), minimum 18.55 GW (2024-05-05 06:00). Monthly peaks (GW): Jan 46.8, Feb 49.9, Mar 47.9, Apr 35.6, May 36.5, Jun 46.1, Jul 57.0, Aug 54.4, Sep 53.9, Oct 43.4, Nov 40.2, Dec 44.7. Source: TEPCO でんき予報 past data `juyo-2024.csv` (https://www.tepco.co.jp/forecast/html/images/juyo-2024.csv).

## 8. Residential and C&I flexibility

- [VERIFIED] **Home and stationary Li-ion battery shipments (JEMA, 14 manufacturers):**
  - FY2025: **153,645 units / 1,545,250 kWh** (average **10.06 kWh/unit**). FY2024: 158,852 units / 1,526,682 kWh.
  - **Cumulative FY2013–FY2025: 1,136,132 units / about 9.57 GWh.**
  - Hybrid PV-plus-battery inverters were **89.7%** of FY2025 units.

  Source: JEMA (2026-06-05). https://www.jema-net.or.jp/stat/evefa20000004v9u-att/libsystem_FY2025.pdf
- [VERIFIED] **Residential PV (<10 kW), end-March 2026:**
  - FIT-era: **12.904 GW across 2,610,053 systems**.
  - Transferred from the pre-2012 scheme: 4.724 GW across 1,196,298 systems.
  - [ESTIMATE] Total about **17.6 GW / 3.81 million systems** (sum of the two rows).

  Source: METI FIT portal. https://www.fit-portal.go.jp/PublicInfoSummary
- [VERIFIED] **卒FIT (post-FIT):** ANRE projected about **1.65 million installations / 6.7 GW** leaving FIT cumulatively by 2023. This is a projection; no actual count was found. Source: https://www.enecho.meti.go.jp/about/special/johoteikyo/taiyoko_manryo.html
- [VERIFIED] **Aggregator licence (特定卸供給事業者, created April 2022 under the amended Electricity Business Act):** **172 registered** as of 2026-09-01 (30 transitional + 142 new). Source: ANRE list. https://www.enecho.meti.go.jp/category/electricity_and_gas/electricity_measures/009/list/aguri-list.html
- [VERIFIED] **Low-voltage resources in the balancing market:**
  - From **FY2026**, low-voltage resources measured at the customer's meter can enter **all balancing products** as aggregated lists (リスト・パターン).
  - Device-level metering (機器個別計測) is allowed for low voltage from FY2026 where a next-generation smart meter is installed. High-voltage resources under 1 MW follow from FY2027.
  - Primary reserve at device level is not available at the start of FY2026.

  Source: OCCTO 第57回需給調整市場検討小委員会 資料3 (2025-09-26), pp.31–34. https://www.occto.or.jp/assets/iinkai/chouseiryoku/jukyuchousei/2025/files/jukyu_shijyo_57_03.pdf
- [VERIFIED] **TEPCO EP residential DR, "エコ・省エネチャレンジ" 2026:**
  - Load-reduction windows: 2026-07-01 to 10-09 and 2026-12-01 to 2027-02-26.
  - Load-increase (上げDR) windows: 2026-04-01 to 05-31 and 2026-10-01 to 11-01.
  - Points per event vary and are notified by email. 1 point = 1 JPY equivalent (via dotmoney, from 300 points).
  - Success means at least 0.01 kWh against an ERAB-guideline baseline.

  Source: https://www.tepco.co.jp/ep/private/savingenergy/lp/ecochallenge.html
- [ESTIMATE] **Residential DR payment:** about **5 JPY/kWh** reduced normally, and about **20 JPY/kWh** during supply-tightness events. Basis: secondary reports of TEPCO EP point rates, not confirmed on the TEPCO page.
- [VERIFIED] **Capacity-market DR (発動指令電源), FY2029 auction:**
  - **7.15 GW bid** (4.2% of bids), 89.4% win rate.
  - Weighted-average DR bid **54 JPY/kW-yr**; at least 96.2% of DR bids were at 0 JPY/kW.
  - DR is capped at 4% of H3 demand in the main auction. It must deliver for 3 hours when called.

  Source: OCCTO. https://www.occto.or.jp/assets/iinkai/youryou_kentoukai/71/youryou_kentoukai_71_03.pdf
- [VERIFIED] **DR-ready requirements (METI):**
  - Home batteries and hybrid water heaters must have gateway and cloud connectivity, accept and execute charge/discharge commands at **30-minute or shorter intervals**, and meet JC-STAR ★1 security. Finalised 2025-11-25. https://www.meti.go.jp/shingikai/energy_environment/dr_ready/pdf/007_03_00.pdf
  - JEMA roadmap: JEM standard in FY2027, products from FY2028, all makers from **FY2029**. https://www.meti.go.jp/shingikai/energy_environment/dr_ready/pdf/007_04_00.pdf
  - Heat-pump water heater target year is "around 2030". https://www.meti.go.jp/shingikai/energy_environment/dr_ready/pdf/003_03_00.pdf
- [VERIFIED] **EV stock, end-FY2024:** **358,262 BEV** and **287,352 PHEV** (passenger). End-FY2023: 301,435 BEV and 252,552 PHEV. Source: NeV / 次世代自動車振興センター. https://www.cev-pc.or.jp/tokei/hoyuudaisu.html
- [ESTIMATE] **BEV+PHEV share of new sales:** about 5% (4.98% in August 2026, from a secondary compilation of JADA data). https://ev-charge-enechange.jp/articles/033/
- [ESTIMATE] **V2H:** subsidised units were about 5,000 per year by FY2023 (FY2023: 4,981). Basis: search snippet only; no primary installed-base figure was found.

## 9. TEPCO Energy Partner (東京電力エナジーパートナー)

- [VERIFIED] **Retail sales:**
  - EP consolidated retail sales were **171.5 TWh in FY2025** (residential 58.8, commercial and industrial 112.7), down from **186.4 TWh in FY2024** (60.1 / 126.3).
  - TEPCO HD's group retail figure is 171.9 TWh in FY2025, down from 187.2. It includes last-resort and island supply.
  - Wholesale sales were 41.3 TWh.

  Sources: https://www.tepco.co.jp/about/ir/library/results/pdf/2603q4gaiyou-j.pdf ; https://www.tepco.co.jp/about/ir/library/presentation/pdf/260430setsu-j.pdf
- [VERIFIED] **Financials:** EP revenue **4.99 trillion JPY** in FY2025 (FY2024: 5.56 trillion JPY). Ordinary profit **254.9 bn JPY** (FY2024: 287.9 bn JPY). The decline came from lower volume and higher procurement cost. Gas customers numbered about **1.51 million** in March 2026. Sources: same.
- [VERIFIED] **Electricity customer contract counts:** not published since FY2014, so no figure is available.
- [ESTIMATE] **Electricity customer base:** on the order of **20 million low-voltage accounts** in the Kanto area. Basis: TEPCO EP's residential volume of 58.8 TWh ÷ about 3,000 kWh per household per year gives about 19.6 million. Treat this as a scale anchor for synthetic data, not a reported figure.
- [VERIFIED] **エネカリ (TEPCOホームテック):**
  - Solar, batteries, エコキュート heat-pump water heaters, IH cooktops and V2H.
  - **0 JPY upfront** and a fixed monthly fee; the equipment is handed over free at the end of the term.

  Source: https://www.tepco-ht.co.jp/enekari/
- [ESTIMATE] **エネカリ installed base:** more than 55,000 cumulative solar/battery installations by March 2026. Basis: search snippet, not read on the page.
- [VERIFIED] **Residential DR (エコ・省エネチャレンジ, via the くらしTEPCO web service):** points per kWh saved (winter and summer) or shifted into solar hours (spring and autumn). About **1.2 million participants** as of October 2025. Sources: https://kurashi-idea.tepco.co.jp/entry/20260716/july-03 ; https://www.tepco.co.jp/ep/private/savingenergy/lp/ecochallenge.html
- [VERIFIED] **VPP direction:** the FY2025 results presentation says TEPCO will aggregate customer-side batteries for supply capacity and balancing, and targets more than 60% decarbonised supply by FY2040. No MW figure is given. Source: https://www.tepco.co.jp/about/ir/library/presentation/pdf/260430setsu-j.pdf
- [VERIFIED] **Procurement shift, April 2026:** TEPCO EP's April 2026 tariff revision says its procurement "changes significantly from April 2026". It moved fuel adjustment to a 1-month average. This lines up with EGC's statement that a large long-term PPA ended at the end of March 2026 (section 1.6). Source: https://www.tepco.co.jp/ep/corporate/plan_h/minaoshi_2026.html
- [ESTIMATE] The PPA that ended is the **TEPCO EP–JERA** contract. Basis: Nikkei (https://project.nikkeibp.co.jp/energy/atcl/19/feature/00001/00119/) and jepsolution.jp; not confirmed in a primary source.
- [VERIFIED] **TEPCO PG area profile:** see section 7. Area demand is about 268 TWh/yr. The summer peak is about 57 GW at 13–15h. The winter peak is about 50 GW with morning (8–9h) and evening (17–19h) humps. Solar peaks at about 17–18 GW.

## 10. Mitsubishi Electric (三菱電機)

- [VERIFIED] **Serendie:** launched **2024-05-29** as Mitsubishi Electric's digital co-creation platform, the core of its shift to a "Circular Digital-Engineering Company". Focus areas: carbon neutral, circular economy, safety/security, inclusion, well-being. https://www.mitsubishielectric.com/en/pr/2024/0529-b/
- [VERIFIED] (trade press) **Serendie scope:** brings together data from existing business platforms:
  - BLEnDer (power/energy)
  - Ville-feuille (buildings/elevators)
  - Linova (HVAC/appliances)
  - INFOPRISM (rail)
  - e-F@ctory (factory automation)

  Partner technologies shown in July 2024: Snowflake, Dataiku, MuleSoft/Salesforce. https://cloud.watch.impress.co.jp/docs/news/1607892.html
- [VERIFIED] **Serendie targets:** "Serendie-related business" revenue of **¥1.1T in FY2030**, up from about ¥640B in FY2023. **4,000** DX staff were consolidated into the new Digital Innovation BU (May 2025). https://www.mitsubishielectric.co.jp/ja/pr/2025/pdf/0528-1.pdf
- [VERIFIED] **Mid-term strategy (2026-05-29):**
  - **Solution-business revenue ¥0.4T (FY2025) → ¥1.0T (FY2030)**, with operating margin 7% → 15%.
  - Company adjusted operating margin **12% or more** by FY2030.
  - **20,000** DX/AX staff.
  - "Energy management" named a priority business within Infrastructure.

  https://www.mitsubishielectric.co.jp/ja/pr/2026/pdf/0529_co1.pdf
- [VERIFIED] **Serendie Street:**
  - Yokohama site fully opened **2025-01-17**, with about 300 DX staff since October 2024. The first site, YDB, opened in March 2024. https://www.mitsubishielectric.com/en/pr/2025/0117/
  - [ESTIMATE] Boston (Kendall Square) grand opening 2026-06-04; press page returned 403, taken from search text.
- [VERIFIED] **ICONICS** (Foxborough, MA; SCADA/HMI; products GENESIS64, Hyper Historian, MobileHMI):
  - 100% acquired in **May 2019** (ICONICS release dated 2019-05-17). Price not disclosed. More than 350,000 installations in over 100 countries. https://iconics.com/pl-PL/News/Press-Releases/2019/Mitsubishi-Electric-Acquisition-ICONICS
  - [ESTIMATE] Renamed **Mitsubishi Electric Iconics Digital Solutions** from 2025-04-01. Search snippet; the new name does appear on the product page below.
- [VERIFIED] **ICONICS Energy AnalytiX:** real-time energy monitoring and analysis covering cost, consumption and carbon reports and drill-down into abnormal use. It connects to BMS, SCADA and ERP. It was a GENESIS64 add-on and its functions are now standard in the new GENESIS. https://iconics.com/products/energy-analytix
- [VERIFIED] **Nozomi Networks (OT cybersecurity):** acquisition closed **2026-01-28**. Nozomi revenue: $74.7M (2024), $101.7M (2025). https://www.mitsubishielectric.com/en/pr/2026/pdf/0129.pdf
  - [ESTIMATE] Price about $883M for the remaining 93% (search snippet).
- [VERIFIED] **ME96SSEB-MB multi-measuring meter:**
  - Active energy **Class 0.5S (IEC 62053-22)**; current, voltage and power **±0.5%**.
  - **Modbus RTU**. Size 96 × 96 mm. Display update 0.5 s or 1 s.
  - For **CC-Link, Modbus TCP**, analog or digital I/O and logging, use the ME96SSHB-MB or ME96SSRB-MB with option modules.

  https://dl.mitsubishielectric.com/dl/fa/document/manual/pmd/ib63e77/ib63e77a.pdf
- [VERIFIED] **EcoWebServerIII:** an all-in-one server that collects, stores and displays data from Mitsubishi Electric energy-saving devices in a web browser. https://us.mitsubishielectric.com/fa/en/products/pmng/energy-saving-devices/ecoserver/
- [VERIFIED] **EcoMonitorLight and EcoMonitorPlus:** Light is low-cost with a built-in display. Plus is modular and covers power, CO₂ and predictive maintenance. The page documents Modbus RTU. Software: EcoAdviser. https://www.mitsubishielectric.co.jp/fa/products/pmng/ems/items/ecomonitor/index.html
- [VERIFIED] **MELSOFT iQ AppPortal:** central management of MELSOFT (GX Works3 etc.) project files, with version history and branching. https://us.mitsubishielectric.com/fa/en/products/sft/melsoft/iq-app-portal/iq-app-portal/
- [VERIFIED] **e-F@ctory:** Mitsubishi Electric's FA-IT concept in three layers: shop floor, edge, and IT (SCADA/cloud). https://www.mitsubishielectric.com/fa/solutions/efactory/index.html
- [VERIFIED] **Own-factory FEMS case (Nagoya Works E4 building):** about **10%** energy saving from PLC-based control alone, and about **30%** combined with premium motors and high-efficiency transformers. Equipment: MELSEC iQ-R, CC-Link IE Field, MC Works SCADA, EcoMonitorPro, FR-F800. https://www.mitsubishielectric.com/fa/our-stories/029/index.html
- [VERIFIED] **BLEnDer:** power-market software packages sold since 2003. Modules include:
  - AC (aggregation), DR, RE (renewables + storage)
  - AN (active network management), LF (load forecast)
  - PM, BM, Trader
  - smart-meter systems

  https://www.mitsubishielectric.co.jp/ictpowersystem/business/solution1.html
- [VERIFIED] **Large battery control reference:** the **Kita-Toyotomi substation (Hokkaido), 240 MW / 720 MWh**, planned for FY2023 operation, for wind integration. It uses power conditioners, containerised Li-ion and **BLEnDer RE**. Mitsubishi Electric's exact scope at Kita-Toyotomi is not stated. https://www.mitsubishielectric.co.jp/ict-power-system/business/solution4/
- [VERIFIED] **Hyperscaler partnerships:** an **AWS MOU on 2025-01-14** (data-center products, AI platforms for Serendie including multi-agent orchestration). The May 2025 deck names AWS and Microsoft ("Co-Engineering") as hyperscaler partners. **No Google Cloud partnership found** (searched in English and Japanese, 2024–2026). https://www.mitsubishielectric.com/en/pr/2025/0114-a/ ; https://www.mitsubishielectric.co.jp/ja/pr/2025/pdf/0528-1.pdf
- [VERIFIED] **Scale, FY2025 (year ended March 2026):**

  | | Revenue | Operating profit |
  |---|---|---|
  | Group | **¥5,894.7B** | ¥433.0B (¥538.4B excluding a one-off charge) |
  | Infrastructure | ¥1,463.4B | — |
  | ↳ Energy Systems | ¥473.3B | — |
  | Industry & Mobility | ¥1,673.8B | — |
  | ↳ FA Systems | ¥798.2B | — |
  | Digital Innovation | ¥158.0B | — |

  https://www.mitsubishielectric.co.jp/ja/pr/2026/pdf/0428_co2.pdf

## 11. Google technology and Powerledger

- [VERIFIED] **AlphaEvolve:** announced **2025-05-14** (DeepMind blog). It is a Gemini-powered (Flash + Pro) evolutionary coding agent with automated evaluators. Results:
  - recovered about **0.7%** of Google's worldwide compute (Borg scheduling heuristic);
  - 4×4 complex matrix multiplication in **48** scalar multiplications;
  - **23%** kernel speedup (1% less Gemini training time);
  - up to **32.5%** FlashAttention speedup.

  https://deepmind.google/discover/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/
- [VERIFIED] **AlphaEvolve on Google Cloud:** private preview / Early Access on **2025-12-10**, which listed "smart grid load balancing" as an example. **Generally available from 2026-07-10** on Google Cloud (Gemini Enterprise Agent Platform). The GA post names customers (BASF, FM Logistic, Kinaxis) but no energy or utility use cases.
  - https://cloud.google.com/blog/products/ai-machine-learning/alphaevolve-on-google-cloud
  - https://cloud.google.com/blog/products/ai-machine-learning/alphaevolve-is-available-for-everyone (GA date checked directly by this analyst)
- [VERIFIED] **WeatherNext 2 (2025-11-17):**
  - Functional Generative Network; **8× faster**; under 1 minute per forecast on one TPU.
  - Beats the first-generation WeatherNext on **99.9%** of variables and lead times (0–15 days).
  - Available in **Earth Engine and BigQuery**, with Vertex AI early access.
  - Resolution conflict: the blog says "up to 1-hour", while the developer docs list **0.25°, 6-hour steps, 64 members**.

  https://blog.google/innovation-and-ai/models-and-research/google-deepmind/weathernext-2/ ; https://developers.google.com/weathernext/guides/models
- [VERIFIED] **WeatherNext 3 exists.** It was announced **2026-09-03**.
  - **New forecast every hour**, using geostationary satellite data.
  - Resolution: **5 km** for surface temperature and moisture, 10 km for other surface variables, 25 km for atmospheric variables.
  - Clean-energy outputs: **100 m wind**, cloud cover and solar radiation.
  - Available via BigQuery, Earth Engine and Cloud Storage.
  - Developer docs list: 0.05° (stations), 0.1° (surface) and 0.25° (pressure levels); 1-hour steps; **15-day** lead time; 64 members; 24 runs per day.

  https://blog.google/innovation-and-ai/models-and-research/google-deepmind/introducing-weathernext-3/ (checked directly by this analyst) ; https://developers.google.com/weathernext/guides/models
- [VERIFIED] **Google Distributed Cloud (GDC) connected:**
  - Runs GKE clusters and VMs on Google-certified hardware on customer premises, managed from Google Cloud.
  - **Japan is one of 29 countries** where it is sold. Hardware: Dell XR11 (G1) and XR8000r (G2) servers.
  - Next '26 (2026-04-23) added Gemini Flash (preview) on GDC connected with NVIDIA Blackwell.
  - NTT DATA has been a reseller of the **air-gapped** version in Japan since 2025-07-10.

  https://docs.cloud.google.com/distributed-cloud/connected/latest/docs/order ; https://cloud.google.com/blog/topics/hybrid-cloud/google-distributed-cloud-at-next26 ; https://www.telecompaper.com/news/ntt-data-becomes-google-distributed-cloud-air-gapped-reseller--1541954
- [VERIFIED] **Vertex AI Agent Engine:** GA **2025-03-04**. In **April 2026** Vertex AI was renamed **Gemini Enterprise Agent Platform**, and Agent Engine's runtime became "Agent Runtime" (alongside Memory Bank and Sessions). ADK was open-sourced on 2025-04-09.
  - https://docs.cloud.google.com/vertex-ai/generative-ai/docs/release-notes
  - https://cloud.google.com/blog/products/ai-machine-learning/introducing-gemini-enterprise-agent-platform
  - https://developers.googleblog.com/en/agent-development-kit-easy-to-build-multi-agent-applications/
- [VERIFIED] **Earth Engine:**
  - Commercially available on Google Cloud since **2022-06-28**. https://blog.google/products-and-platforms/products/earth/introducing-earth-engine-for-governments-and-businesses/
  - Open Buildings V3 does **not cover Japan**. https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings_v3_polygons
  - MODIS MCD18A1 provides 3-hourly shortwave radiation at 1 km. https://developers.google.com/earth-engine/datasets/catalog/MODIS_062_MCD18A1
- [VERIFIED] **Powerledger in Japan:**
  - Kansai Electric Power P2P trial announced **2018-04-24** (Osaka, up to 10 homes). https://powerledger.io/media/powerledger-kansai-electric-power-co-to-trial-peer-to-peer-renewable-energy-trading-in-japan/
  - Results published 2019-08-12 for post-FIT surplus solar: automated trading and settlement, with legal changes needed for commercial use. https://powerledger.io/media/powerledger-and-kepco-bring-p2p-energy-trading-to-osaka-japan/
  - Extended to renewable-energy and non-fossil certificate tracking from December 2019 to March 2020. https://powerledger.io/media/powerledger-kepco-extend-trial-to-create-and-track-renewable-energy-credits/
  - Selected for a Tokyo Metropolitan Government green-finance programme (2023-10-16). https://powerledger.io/powerledger-joins-tokyos-prestigious-green-finance-initiative/
  - **No 2024–2026 Japan project found.**
- [ESTIMATE] **Powerledger and Sharing Energy:** partnership in January 2019 to track about 100 customers in Kansai, Chubu and Kyushu. Basis: search snippet (BusinessWire returned 403).

## 12. Battery economics

- [VERIFIED] **Round-trip efficiency:** NREL ATB 2024 utility-scale Li-ion assumptions are **85%** round-trip, about 1 cycle/day, a 15-year life, fixed O&M of 2.5% of capex, and augmentation included. Source: https://atb.nlr.gov/electricity/2024/utility-scale_battery_storage
- [VERIFIED] **Japan capex (MRI for METI, 2025-03-07):**
  - **Grid-scale** (FY2024 subsidy data): system **5.4万円/kWh** (cells 4.1, PCS 0.6) plus construction **1.4万円/kWh**, so about **68,000 JPY/kWh** all-in. That is 0.8万円/kWh lower than FY2023. Unsubsidised imported systems are quoted at 2–4万円/kWh.
  - **C&I:** 9.2 + 1.4万円/kWh.
  - **Residential:** 11.1 + 1.0万円/kWh (15–20万円/kWh unsubsidised).
  - Projection for a 100 MW system: **5.0 → 3.9万円/kWh** from FY2023 to FY2030.

  Source: https://www.meti.go.jp/shingikai/energy_environment/storage_system/pdf/20250307_1.pdf
- [ESTIMATE] **Degradation cost per kWh throughput:** capex ÷ lifetime cycles, assuming about 6,000 full cycles and no residual value.
  - Grid-scale all-in: 68,000 ÷ 6,000 ≈ **11 JPY/kWh**.
  - Grid-scale cells only: 41,000 ÷ 6,000 ≈ **7 JPY/kWh**.
  - Residential: 121,000 ÷ 5,475 ≈ **22 JPY/kWh**.
  - Recommended sim value: **7–10 JPY/kWh discharged** for grid-scale (marginal wear, excluding sunk balance-of-plant).
- [VERIFIED] **Long-term decarbonisation auction (長期脱炭素電源オークション), batteries:**
  - **Round 1** (FY2023 bids, results 2024-04-26): batteries bid **4.559 GW** with a **24%** win rate [ESTIMATE ≈ 1.09 GW awarded]. Batteries plus pumped hydro awarded 1.669 GW. The total auction awarded 9.766 GW.
  - **Round 2** (FY2024 bids, results 2025-04-28): batteries bid **6.956 GW** with a **20%** win rate [ESTIMATE ≈ 1.37 GW, consistent with the reported 27 projects / 1.37 GW].
  - **Round 3** (FY2025 bids, results 2026-05-13): batteries awarded **1.251 GW** (46% win rate). The round required **6 hours or more** duration, with a 40万kW cap per storage group, single-country cell share under 30%, a 5万kW minimum, and a cap-price threshold raised to 20万円/kW-yr.
  - Battery-specific clearing prices are not published.

  Sources: OCCTO result PDFs:
  - https://www.occto.or.jp/assets/market-board/market/oshirase/2024/files/240426_longauction_youryouyakujokekka_kouhyou_ousatsu2023.pdf
  - https://www.occto.or.jp/assets/market-board/market/oshirase/2025/files/250428_longauction_youryouyakujokekka_kouhyou_ousatsu2024.pdf
  - https://www.occto.or.jp/assets/various/capacity-market/jitsujukyukanren/2025_boshuyoukou_long/260513_longauction_youryouyakujokekka_kouhyou_ousatsu2025.pdf
  - https://www.occto.or.jp/assets/market-board/market/files/202507_youryou_gaiyousetsumei_long.pdf
- [ESTIMATE] **Implied average LTDA price** for all decarbonised sources (total contract value ÷ capacity): about **58,300** (R1), **68,900** (R2) and **111,400 JPY/kW-yr** (R3). Basis: OCCTO totals.
- [VERIFIED] **Grid-battery connection queue:**
  - End-June 2025: connection studies about **143 GW**, contract applications about **18 GW**, connected only about **0.25 GW**.
  - End-December 2025: contract applications **28.69 GW** across 3,759 projects. Tokyo area **5.17 GW**, Kyushu 5.90, Tohoku 4.92.
  - Stricter deposit rules apply from April 2026.

  Sources: https://www.meti.go.jp/shingikai/enecho/denryoku_gas/saisei_kano/smart_power_grid_wg/pdf/004_04_00.pdf ; https://www.meti.go.jp/shingikai/enecho/denryoku_gas/saisei_kano/smart_power_grid_wg/pdf/007_01_01.pdf
- [VERIFIED] **Capacity market treatment:** batteries count as stable supply only with **3 hours or more** of discharge. Batteries bid 1.69 GW into the FY2029 main auction. Source: OCCTO FY2029 results.
- [VERIFIED] (computed) **Tokyo battery grid output** was only about 45–75 MW maximum in FY2025–FY2026 in the TEPCO area supply-demand data, so grid batteries are still negligible in dispatch. Source: TEPCO PG eria_jukyu CSVs.
- [VERIFIED] (computed) **Tokyo daily spot arbitrage spreads.** Each day, the mean of the top-N slots minus the mean of the bottom-N slots, with no ordering constraint (an upper bound).

  | FY | 2 h spread (N=4): mean / median / p10 / p90 | 4 h spread (N=8): mean / median / p10 / p90 |
  |---|---|---|
  | 2023 | 8.66 / 7.55 / 4.19 / 14.51 | 7.66 / 6.77 / 3.74 / 13.69 |
  | 2024 | 8.77 / 8.06 / 4.77 / 13.90 | 7.89 / 7.45 / 4.14 / 12.23 |
  | 2025 | **8.28 / 7.34 / 3.94 / 14.12** | **7.25 / 6.31 / 3.41 / 12.41** |
  | 2026 (Apr–Sep 27) | **18.35** / 15.89 / 9.79 / 31.12 | 15.41 / 13.97 / 8.32 / 25.39 |

  Units: JPY/kWh. Source: JEPX spot CSV.
- [ESTIMATE] **Perfect-foresight wholesale-only arbitrage for a 2-hour battery (Tokyo):** assumes 1 cycle/day, 85% round-trip efficiency, buy at the mean of the 4 cheapest slots, sell at 0.85 × the mean of the 4 dearest slots.
  - FY2025: **about 5.7 JPY per kWh of capacity per day**, or about **2,080 JPY/kWh-cap/yr**.
  - FY2024: about 2,190 JPY/kWh-cap/yr.
  - FY2026 to date: about 13.6 JPY/kWh-cap/day.

  Basis: my calculation on JEPX data. Real bots capture perhaps 60–80% of perfect foresight. This is an upper bound on the kWh-only revenue stack, excluding balancing-market and capacity revenue.

---

## Known gaps and caveats

- **JEPX spot bid-price cap:** no hard cap was found in JEPX's trading rules (取引規程). The simulator cap below is an assumption.
- **Imbalance curve between B (10%) and B' (8%):** the value at the start point is interpreted as "no uplift". This is not restated verbatim in a primary source.
- **TEPCO EP customer counts:** electricity contract counts are not published. Battery-specific clearing prices in the long-term decarbonisation auction (LTDA) are not published.
- **Hourly or 30-minute non-fossil certificates:** there is no government scheme. Only private pilots exist (section 6.3).
- **Mitsubishi Electric and Google Cloud:** no partnership was found. Mitsubishi Electric's disclosed hyperscaler partners are AWS and Microsoft.
- **Stale sources:** several METI/EGC pages rate-limit automated access. Where a figure came only from a search snippet, it is tagged [ESTIMATE].
- **FY2026 figures are partial:** computed statistics cover 2026-04-01 to 2026-09-27 (spot) or to 2026-08-31 (TEPCO area supply-demand). They reflect the Middle-East fuel shock regime.

## Machine-readable simulation parameters

```yaml
simulation_parameters:
  meta:
    as_of: "2026-09-26"
    currency: JPY
    time_resolution: "30-min settlement slots (48/day), JST"
    fiscal_year: "April-March (FY2025 = 2025-04-01..2026-03-31)"
  jepx_spot:
    slots_per_day: {value: 48, unit: "30-min products", source: "JEPX 取引規程 Art.14 https://www.jepx.jp/electricpower/outline/pdf/tr_rules.pdf"}
    gate_closure: {value: "10:00 JST D-1", source: "JEPX 取引規程 Art.16"}
    bid_window_open: {value: "00:00 JST D-11", source: "JEPX 取引規程 Art.16"}
    auction: {value: "blind uniform-price (single-price) double auction with market splitting into 9 areas", source: "JEPX 取引規程 Art.17-18"}
    price_tick: {value: 0.01, unit: "JPY/kWh", source: "JEPX 取引規程 Art.15"}
    lot_size: {value: 50, unit: "kWh per 30-min product", source: "JEPX 取引規程 Art.15"}
    price_floor: {value: 0.01, unit: "JPY/kWh", source: "observed minimum in JEPX spot CSV"}
    price_cap_for_sim: {value: 999.99, unit: "JPY/kWh", basis: "ESTIMATE - no hard cap found in 取引規程; historical max 252.00 (Tokyo 2021-01-15)"}
    system_price_annual_mean: {unit: "JPY/kWh", FY2019: 7.93, FY2020: 11.20, FY2021: 13.45, FY2022: 20.38, FY2023: 10.74, FY2024: 12.31, FY2025: 11.08, source: "JEPX Business Reports BR2024/BR2025"}
    tokyo_area_annual_mean: {unit: "JPY/kWh", FY2020: 12.02, FY2021: 14.27, FY2022: 23.50, FY2023: 12.20, FY2024: 13.66, FY2025: 12.45, FY2026_Apr_Sep: 20.36, source: "computed from JEPX spot_summary CSV"}
    tokyo_regime_for_sim:
      baseline_FY2025: {mean: 12.45, p5: 7.96, median: 11.53, p95: 19.43, unit: "JPY/kWh", source: "computed JEPX CSV"}
      fuel_shock_FY2026: {mean: 20.36, p5: 10.27, median: 19.34, p95: 32.39, unit: "JPY/kWh", source: "computed JEPX CSV (Apr 1-Sep 27 2026)"}
    tokyo_hourly_shape_FY2025_JPYkWh:
      spring: [12.5,12.3,12.3,12.5,12.7,12.9,12.8,11.8,11.0,10.8,9.5,8.8,8.1,9.4,10.4,11.8,13.6,15.0,16.0,15.6,14.9,14.3,14.1,13.2]
      summer: [11.7,11.3,11.2,11.2,11.2,11.1,10.8,10.7,10.7,11.7,11.5,11.9,11.3,13.7,14.9,16.0,18.3,18.5,18.3,17.1,15.6,13.9,13.4,12.2]
      autumn: [11.4,11.1,11.1,11.3,11.4,11.7,12.6,12.0,11.3,11.3,10.8,10.6,10.1,11.3,12.3,14.0,16.4,16.1,15.5,15.0,14.4,13.0,12.5,11.7]
      winter: [10.5,10.4,10.4,10.3,10.4,10.7,12.4,13.9,12.9,11.5,10.2,9.3,8.8,9.3,9.8,11.0,13.3,14.2,14.0,13.5,13.3,12.6,11.9,11.0]
      source: "computed from JEPX spot CSV (hour-of-day mean of two 30-min slots, hour 0 = 00:00-01:00)"
    kyushu_spring_hourly_FY2025_JPYkWh: {value: [9.6,9.3,10.0,11.0,11.3,11.4,11.1,8.6,6.6,5.1,3.9,2.9,2.1,3.0,3.9,5.6,8.2,11.6,13.9,13.5,13.0,12.3,11.6,10.1], source: "computed JEPX CSV"}
    floor_0p01_probability: {tokyo_FY2025: 0.006, kyushu_FY2025: 0.056, kyushu_spring_midday_peak_month_share: "Apr 252 slots / 1440", unit: "fraction of slots", source: "computed JEPX CSV"}
    weekend_discount_tokyo: {value: -2.03, unit: "JPY/kWh vs weekday mean (FY2025)", source: "computed JEPX CSV"}
    tokyo_minus_system_mean: {FY2025: 1.40, FY2026_to_date: 3.75, unit: "JPY/kWh", source: "computed JEPX CSV"}
    daily_log_return_sd_tokyo: {value: 0.145, period: FY2025, source: "computed JEPX CSV"}
    slot_autocorr_lag1: {value: 0.94, source: "computed JEPX CSV FY2025"}
    slot_autocorr_lag48: {value: 0.66, source: "computed JEPX CSV FY2025"}
    intraday_range_mean_tokyo: {FY2025: 9.45, FY2026_to_date: 22.03, unit: "JPY/kWh (daily max-min)", source: "computed JEPX CSV"}
    price_netload_slope: {FY2025: {intercept: 2.04, slope: 0.357}, FY2026_Apr_Aug: {intercept: 1.23, slope: 0.699}, unit: "JPY/kWh = a + b * (TEPCO demand - PV) in GW", source: "computed JEPX + TEPCO PG eria_jukyu CSVs"}
    spike_scenarios:
      - {name: "Jan-2021 cold snap / LNG shortage", peak: 252.0, daily_mean_peak: 167.0, duration_days: "~3 weeks elevated", unit: "JPY/kWh (Tokyo)", source: "JEPX CSV; EGC 2021 report"}
      - {name: "Mar-2022 需給ひっ迫警報", plateau: 80.0, daily_mean_peak: 76.7, source: "JEPX CSV"}
      - {name: "Jun-2022 heatwave 注意報", peak: 200.0, daily_mean_peak: 86.1, source: "JEPX CSV"}
      - {name: "Apr-2026+ Middle East fuel shock", peak: 64.28, monthly_mean: "18-23", source: "JEPX CSV; EGC 021_03"}
  jepx_intraday:
    mechanism: {value: "continuous (zaraba), opens 17:00 D-1, gate closure 1h before delivery", source: "JEPX 取引規程 Art.63"}
    premium_vs_system_price: {FY2025_mean: 0.68, FY2025_sd: 1.71, FY2026_mean: 1.07, FY2026_sd: 4.63, unit: "JPY/kWh", source: "computed JEPX intraday CSV"}
    in_slot_high_low_range: {FY2025_mean: 8.80, FY2025_median: 6.92, unit: "JPY/kWh", source: "computed JEPX intraday CSV"}
    liquidity: {FY2025_volume_GWh: 6802, avg_MWh_per_slot: 388, avg_trades_per_slot: 176, source: "JEPX BR2025; computed CSV"}
    new_system_go_live: {value: "2026-10-01 delivery", source: "JEPX notice 2026-09-08"}
  imbalance:
    base_price: {value: "marginal kWh price of wide-area dispatched balancing, corrected by intraday price P; 0 JPY/kWh when VRE curtailed & system long", source: "METI/EGC 中間とりまとめ 2019"}
    scarcity_curve:
      index: "広域予備率 (wide-area reserve margin) at GC"
      points_pct: {B_start: 10, B_prime_D: 8, A_C: 3}
      D_value: {until_2026_09_30: 45, from_2026_10_01: 50, unit: "JPY/kWh"}
      C_value: {FY2022_to_2026_09_30: 200, from_2026_10_01: 300, long_run_principle: 600, unit: "JPY/kWh"}
      interpolation: {value: "linear 10%->8% (0->D), 8%->3% (D->C), flat C below 3%", basis: "ESTIMATE from 'linear formula' description"}
      cumulative_threshold: {trigger: ">=30 slots with area price >=200 JPY/kWh in prior 7 days", reduced_cap: 100, release: "0 slots >=100 JPY/kWh in prior 7 days", unit: "JPY/kWh", source: "EGC 008_04_01"}
      source: "METI 022_07_02; EGC 008_04_01; energy-advisor imb-price2-2"
    tokyo_imbalance_minus_spot: {FY2025_mean: -0.68, FY2025_sd: 4.93, FY2025_p5: -7.67, FY2025_p95: 5.72, FY2026_sd: 9.42, unit: "JPY/kWh", source: "computed from imbalanceprices-cs.jp + JEPX CSV"}
    tokyo_imbalance_zero_price_share: {FY2025: 0.040, unit: "fraction of slots at 0.00", source: "computed (694/17453)"}
    single_price: {value: true, basis: "surplus and shortage prices identical in every slot checked FY2024-FY2026"}
  balancing_market:
    products:
      FCR_一次: {response: "10 s", duration: "5 min", signal: "self (GF)"}
      SFRR_二次1: {response: "5 min", duration: "30 min", signal: "LFC"}
      FRR_二次2: {response: "5 min", duration: "30 min", signal: "EDC"}
      RR_三次1: {response: "15 min", duration: "30 min", signal: "EDC"}
      RRFIT_三次2: {response: "60 min", duration: "30 min", signal: "online"}
      min_bid_MW: 1
      block: "30 min"
      source: "EPRX 商品要件 第6版 2026-03-13"
    schedule: {bid_window: "11:30-14:00 D-1", clearing_by: "15:00 D-1", since: "2026-03-14 (all products day-ahead, 30-min)", source: "EPRX; EGC 021_06_00"}
    combined_market_price_cap: {value: 15, unit: "JPY/ΔkW per 30 min", source: "EGC 021_06_00"}
    tokyo_avg_price_2026:
      combined: {Apr: 2.68, May: 2.57, Jun: 2.39, unit: "JPY/ΔkW·30min"}
      tertiary2: {Apr: 3.80, May: 12.20, Jun: 4.66, unit: "JPY/ΔkW·30min"}
      source: "EGC 021_06_00"
    tokyo_avg_price_FY2024: {weekly_combined: 4.18, tertiary2: 11.51, unit: "JPY/ΔkW·h", source: "ANRE 108_04_00"}
    battery_clearing_price_FY2024: {combined: 31.39, tertiary2: 330.07, unit: "JPY/ΔkW·h", note: "fell to 22.93 / 58.65 in FY2025 H1", source: "ANRE 108_04_00"}
  retail_cost_stack_tepco_area:
    wheeling_high_voltage_standard:
      until_2026_10_31: {basic_JPY_per_kW_month: 653.87, energy_JPY_per_kWh: 1.84}
      from_2026_11_01: {basic_JPY_per_kW_month: 762.44, energy_JPY_per_kWh: 1.84}
      source: "TEPCO PG 託送供給等約款 (takusou_yakkan20260213.pdf / 20260911.pdf)"
    wheeling_extra_high_voltage_standard:
      until_2026_10_31: {basic_JPY_per_kW_month: 423.39, energy_JPY_per_kWh: 0.91}
      from_2026_11_01: {basic_JPY_per_kW_month: 446.25, energy_JPY_per_kWh: 0.91}
      source: "TEPCO PG 託送供給等約款"
    wheeling_all_in_1MW_60pctLF: {until_2026_10: 3.3, from_2026_11: 3.6, unit: "JPY/kWh", basis: "ESTIMATE - tariff arithmetic"}
    capacity_contribution_per_kWh_tokyo: {FY2024: 1.84, FY2025: 0.50, FY2026: 0.94, FY2028_approx: 2.6, unit: "JPY/kWh", basis: "ESTIMATE - OCCTO Tokyo retailer burden / Tokyo area demand"}
    capacity_price_tokyo_JPY_per_kW_year: {FY2024: 14137, FY2025: 3495, FY2026: 5834, FY2027: 9555, FY2028: 14812, FY2029: 15111, source: "OCCTO main auction results"}
    renewable_surcharge: {FY2023: 1.40, FY2024: 3.49, FY2025: 3.98, FY2026: 4.18, unit: "JPY/kWh (May-Apr billing)", source: "METI press releases"}
    non_fossil_cert_cost: {FIT_cert: 0.40, nonFIT_renewable_designated: 1.21, unit: "JPY/kWh (FY2026 R1)", source: "JEPX nf_summary CSV"}
    tepco_ep_market_linked_plan_FY2026:
      basic_JPY_per_kW_month: 1500
      energy_JPY_per_kWh: {day: 15.18, night: 15.00}
      market_adjustment: "(avg JEPX spot - 11.60) * 1.142 JPY/kWh"
      source: "TEPCO EP 2026minaoshisiryou.pdf"
    tepco_ep_basic_plan_FY2026: {basic_JPY_per_kW_month: 2530, energy_JPY_per_kWh: 17.43, market_adj_coeff: {summer: 0.492, winter: 0.474, other: 0.397}, base_spot: 11.60, source: "TEPCO EP"}
    generic_market_linked_CI:
      formula: "price_slot = JEPX_Tokyo_slot * loss_factor + service_fee + wheeling_energy + capacity_contrib + renewable_surcharge + NFC; plus wheeling basic per kW"
      loss_factor: {value: 1.04, basis: "ESTIMATE"}
      service_fee: {value: 2.0, range: [1.0, 3.0], unit: "JPY/kWh", basis: "ESTIMATE - industry practice"}
    government_subsidy_high_voltage: {Jul_2026: 1.8, Aug_2026: 2.3, Sep_2026: 1.8, unit: "JPY/kWh (deduction)", source: "TEPCO PG press 26x1801"}
  demand_tokyo_area:
    annual_energy_TWh: {FY2024: 267.5, FY2025: 268.3, source: "TEPCO HD FY2025 results"}
    peak_GW: {summer_2025: 57.54, summer_2026: 56.42, winter_FY2025: 50.29, all_time_2001: 64.30, source: "TEPCO でんき予報 / TEPCO HD"}
    min_GW: {FY2025: 18.30, source: "computed TEPCO eria_jukyu"}
    hourly_profile_GW_FY2025:
      summer_JulAug: [29.9,27.9,26.9,26.6,26.6,27.0,29.0,33.0,38.5,42.7,44.6,45.9,45.9,46.7,46.6,46.2,45.6,43.8,42.6,41.3,39.2,37.0,34.9,32.7]
      winter_DecFeb: [30.1,28.9,28.5,28.5,28.9,30.5,33.8,36.9,39.0,39.3,38.1,37.1,35.6,35.7,35.5,35.8,37.1,38.7,39.2,38.8,38.1,36.6,34.6,32.5]
      spring_AprMay: [22.9,21.9,21.9,22.2,22.4,22.5,23.0,24.4,26.7,28.6,29.2,29.5,28.7,29.2,29.1,29.0,29.3,29.4,30.1,29.7,28.6,27.2,25.9,24.5]
      source: "computed TEPCO PG eria_jukyu CSVs"
    pv_profile_GW_FY2025:
      summer_JulAug: [0,0,0,0,0,0.4,2.0,4.7,7.4,9.7,11.2,12.1,12.0,10.8,8.9,6.4,3.5,1.2,0.1,0,0,0,0,0]
      spring_AprMay: [0,0,0,0,0,0.3,1.5,3.8,6.2,8.2,9.5,10.1,9.8,8.9,7.2,5.0,2.6,0.7,0,0,0,0,0,0]
      winter_DecFeb: [0,0,0,0,0,0,0,1.0,4.2,7.3,9.6,10.6,10.5,9.1,6.6,3.4,0.7,0,0,0,0,0,0,0]
      max_GW: 17.84
      annual_share_of_demand: 0.092
      source: "computed TEPCO PG eria_jukyu CSVs"
    supply_mix_FY2025_share: {lng: 0.479, coal: 0.170, imports: 0.141, pv: 0.092, hydro: 0.036, oil: 0.014, bio: 0.012, wind: 0.004, nuclear_FY2026: 0.044, source: "computed TEPCO eria_jukyu"}
    reserve_margin_events:
      - {date: "2022-03-22", type: "需給ひっ迫警報 (first ever)", tokyo_spot_plateau: 80.0, source: "METI 046_03_01; JEPX CSV"}
      - {date: "2022-06-27..30", type: "需給ひっ迫注意報", forecast_reserve_pct: [4.7, 3.7], tokyo_spot_max: 200.0, source: "OCCTO 20220626; JEPX CSV"}
    growth:
      national_peak_GW: {FY2026: 159.6, FY2035: 164.6}
      dc_semicon_additions_GW: {FY2026: 0.83, FY2030: 4.20, FY2035: 7.62}
      tokyo_summer_peak_GW: {FY2026: 55.0, FY2035: 58.9, cagr: 0.008}
      source: "OCCTO 需要想定 2026-01-21"
  flexibility:
    residential_battery_shipments: {FY2025_units: 153645, FY2025_MWh: 1545, avg_kWh_per_unit: 10.06, cumulative_units: 1136132, cumulative_GWh: 9.57, source: "JEMA FY2025"}
    residential_pv: {GW: 17.6, systems_million: 3.81, basis: "ESTIMATE - sum of FIT portal rows"}
    aggregators_registered: {value: 172, as_of: "2026-09-01", source: "ANRE 特定卸供給事業者 list"}
    ev_stock: {BEV: 358262, PHEV: 287352, as_of: "2025-03", source: "NeV/CEV-PC"}
    residential_dr_incentive: {normal: 5, tight_event: 20, unit: "JPY-equivalent points per kWh reduced", basis: "ESTIMATE - secondary reports of TEPCO EP rates"}
    capacity_market_dr_bid: {weighted_avg_JPY_per_kW_year: 54, call_duration_h: 3, source: "OCCTO FY2029 auction"}
    dr_ready_command_interval_max_min: {value: 30, source: "METI DRready WG 2025-11-25"}
  battery:
    round_trip_efficiency: {value: 0.85, unit: "AC-AC", source: "NREL ATB 2024"}
    calendar_life_years: {value: 15, source: "NREL ATB 2024"}
    cycle_life_full_equiv: {value: 6000, basis: "ESTIMATE - LFP typical"}
    capex_grid_scale: {system: 54000, construction: 14000, total: 68000, unit: "JPY/kWh (FY2024 subsidy data)", projection_FY2030: 39000, source: "MRI for METI 2025-03-07"}
    capex_CI: {value: 106000, unit: "JPY/kWh incl. construction", source: "MRI for METI"}
    capex_residential: {value: 121000, unit: "JPY/kWh incl. construction (subsidised)", source: "MRI for METI"}
    degradation_cost: {grid: 8.0, residential: 20.0, unit: "JPY per kWh discharged", basis: "ESTIMATE - capex / cycle life"}
    fixed_om_pct_capex: {value: 0.025, source: "NREL ATB 2024"}
    tokyo_daily_spread_2h: {FY2025_mean: 8.28, FY2026_mean: 18.35, unit: "JPY/kWh", source: "computed JEPX CSV"}
    perfect_foresight_arbitrage_2h: {FY2025: 2080, unit: "JPY per kWh-capacity per year", basis: "ESTIMATE computed"}
    ltda_battery_awards_GW: {round1: 1.09, round2: 1.37, round3: 1.251, note: "round3 requires >=6h", source: "OCCTO LTDA results (R1/R2 estimated from win rates)"}
    grid_battery_queue_GW: {contract_applications_2025_12: 28.69, tokyo: 5.17, source: "METI smart_power_grid_wg 007_01_01"}
  google_tech_context:
    alphaevolve: {announced: "2025-05-14", cloud_preview: "2025-12-10", cloud_GA: "2026-07-10", source: "DeepMind / Google Cloud blogs"}
    weathernext_3: {announced: "2026-09-03", update_frequency: "hourly", surface_resolution_km: 5, other_surface_km: 10, atmos_km: 25, lead_time_days: 15, members: 64, variables: ["100m wind", "cloud cover", "solar radiation", "temperature", "precip"], channels: ["BigQuery", "Earth Engine", "Cloud Storage"], source: "blog.google / developers.google.com/weathernext"}
    google_cfe_japan: {y2024: 0.17, y2025: 0.23, grid_cfe_2025: 0.18, source: "Google Environmental Reports 2025/2026"}
    agent_platform: {value: "Vertex AI renamed Gemini Enterprise Agent Platform (Apr 2026); Agent Engine runtime = Agent Runtime", source: "Google Cloud blog 2026-04-23"}
```
