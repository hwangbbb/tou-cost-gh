# TOU Energy Cost for Ladybug Tools

A single Grasshopper component that prices an EnergyPlus hourly load profile against a time-of-use utility tariff. Feed it the 8,760 hourly electricity (and optionally gas) values that Ladybug Tools reads from an `eplusout.sql`, and it returns annual cost, cost by rate period, an hourly cost collection for LB Hourly Plot and LB Monthly Chart, and monthly peak demand.

Built for Ladybug Tools 1.10.0 in Rhino 8. Works in the Rhino 8 Python 3 component, the IronPython 2 component, and legacy GhPython, because it never handles a Ladybug object directly. See Notes on engines.

## Why this exists

EnergyPlus reports annual energy, not annual cost. Time-of-use tariffs price the same kWh at wildly different rates depending on season, weekday, and hour, so multiplying annual kWh by a blended rate gets the wrong answer for anything with a load shape. This component walks all 8,760 hours, assigns each to the correct rate bucket, and sums. It also reports monthly peak kW, which is the driver for demand-based tariffs.

## Which script to use

| File | Component | Wiring | Use when |
|---|---|---|---|
| `src/tou_cost_v3_direct.py` (v3.1) | legacy GhPython Script, or Rhino 8 Script in IronPython 2 mode | collection in, collection out, no extra components | default choice |
| `src/tou_cost.py` (v2) | any, including Python 3 | LB Deconstruct Data in, LB Load Data out | you must use the Python 3 component |

v3 never imports `ladybug`. It builds every output with `type(_elec_data).from_dict(...)`, so the collections it returns belong to the same class LBT's own components check for, and LB Hourly Plot and LB Monthly Chart accept them directly. See Notes on engines.

## Install

1. Place a Script component. Any of the Rhino 8 Python 3 component, its IronPython 2 mode, or the legacy GhPython Script component works.
2. Create 13 inputs and 5 outputs and name them exactly as in the tables below. Set `_elec_kwh` and `_gas_kwh` to List Access with type hint `float`. Set `summer_mo_` and `peak_hrs_` to List Access. Everything else Item Access, no type hint.
3. Paste the contents of `src/tou_cost.py` into the component.
4. Upstream, put an LB Deconstruct Data on each HB Read Custom Result output and wire its `values` into `_elec_kwh` (and `_gas_kwh`).
5. Downstream, wire `hourly_file` and `monthly_file` each into an LB Load Data component. Those produce real Ladybug collections for the charts.

If a `.ghuser` is present in `examples/`, drag it onto the canvas instead of steps 1 to 3.

## Inputs

| Name | Access | Required | Default | Description |
|---|---|---|---|---|
| `_elec_data` | Item | yes | | Hourly electricity collection(s) in kWh. A list is summed. Other units, kW power, and sub-hourly steps are converted. v2 instead takes 8,760 floats on `_elec_kwh` |
| `_gas_data` | Item | no | none | Hourly gas collection(s), same handling. v2: `_gas_kwh` |
| `peak_summer_` | Item | no | 0.5443 | Summer peak energy rate, $/kWh |
| `peak_winter_` | Item | no | 0.2680 | Winter peak energy rate, $/kWh |
| `offpeak_` | Item | no | 0.0199 | Off-peak energy rate, $/kWh, both seasons |
| `summer_mo_` | List | no | 6, 7, 8, 9 | Months billed at the summer rate |
| `peak_hrs_` | List | no | 8, 22 | Two integers, peak start hour and end hour. End is exclusive, so 8, 22 means 8 a.m. up to but not including 10 p.m. |
| `start_day_of_week_` | Item | no | Sunday | Weekday of January 1 in the simulation run period. Accepts a name (`Sunday`, `sun`) or an integer, 0 = Monday to 6 = Sunday |
| `gas_rate_` | Item | no | 0.0387 | Flat gas rate, $/kWh |
| `demand_rate_` | Item | no | 0 | $/kW applied to each month's peak. Leave unconnected for energy-only tariffs |
| `monthly_charge_` | Item | no | 0 | Fixed monthly customer charge, $ |
| `demand_mult_` | Item | no | 1.0 | Factor converting the hourly-average peak to a billing-interval peak |
| `folder_` | Item | no | system temp | Folder where the two JSON files are written |

Peak days are fixed to Monday through Friday in the script (`PEAK_DAYS`). Every TOU tariff encountered so far uses that convention. Edit the constant if yours does not.

## Outputs

| Name | Type | Wire to | Description |
|---|---|---|---|
| `report` | text | Panel, Multiline Data on | Annual totals by fuel, rates used, four TOU buckets, annual peak |
| `hourly_cost` | 8,760 floats | Panel, spreadsheet | $ per hour, all fuels and charges. Plain numbers |
| `hourly_file` | file path | LB Load Data | Yields two hourly collections: [0] cost in USD, [1] the $/kWh rate in effect each hour |
| `monthly_file` | file path | LB Load Data | Yields two monthly collections: [0] cost in USD, [1] peak demand in kW |
| `peak_times` | 12 strings | Panel | When each month's peak occurred, as `Aug 02 13:00-14:00`, the hour beginning 13:00 |

Charting: take LB Load Data's `data` output from `hourly_file`, pick item 0 with a List Item, and feed it to LB Hourly Plot for an 8,760 heatmap of dollars, or to LB Monthly Chart for monthly bars. Item 1, the hourly rate, plotted the same way is a clean picture of the tariff itself. From `monthly_file`, item 0 goes to LB Monthly Chart for exact monthly cost and item 1 for peak kW.

Demand and fixed charges, when set, are spread evenly across the hours of each month in `hourly_cost` so that the hourly collection still sums to the annual total.

## Getting the data collections

The component reads whatever hourly collection you give it. The upstream chain that produces one from a SQL file is:

1. HB Read Custom Result, with `_sql` pointing at `eplusout.sql` and `_output_names` set to the whole-building outputs present in that file. Common candidates:
   - `Electricity:Facility` and `NaturalGas:Facility` if meters were requested
   - `Facility Net Purchased Electricity Energy` if only output variables were requested and there is no on-site generation
   - `Boiler NaturalGas Energy` for gas when no gas meter exists
2. Confirm the collection header reads `Energy (kWh)` and the collection has 8,760 values. HB Read Custom Result converts from Joules on its own.
3. Put an LB Deconstruct Data on it and wire the `values` output into `_elec_kwh`.

Which output names exist depends entirely on what the model requested. Right-click `_output_names` on HB Read Custom Result to list what the file contains. A name that is not in the file returns an empty branch with no error.

## Method

For each hour `i` of 8,760:

```
month, hour, weekday  <-  from Jan 1 weekday, counting forward
peak  = weekday in Mon..Fri  and  peak_start <= hour < peak_end
season = summer if month in summer_mo_ else winter
rate  = peak_summer_ | peak_winter_ | offpeak_  by (season, peak)
cost_i = kWh_i * rate
```

Hour indexing follows the Ladybug convention: index 0 is the hour beginning at midnight, so a tariff written as "8 a.m. to 10 p.m." maps to hours 8 through 21 inclusive, which is `peak_hrs_ = 8, 22`.

Gas is priced flat at `gas_rate_`. Demand cost, if `demand_rate_` is set, is `sum over months (monthly peak kW * demand_mult_) * demand_rate_`. Fixed charges are `12 * monthly_charge_`.

Monthly peak kW is the largest single hourly kWh value in that month, which equals average kW over that hour. The `peak_times` string gives the hour that value belongs to.

## Rate references

Default values are the Con Edison Small Business Time-of-Use rate as published on the utility's rate page, retrieved 2026-08-31. The full record, including the standard-rate comparison and the customer charge, is in `rates/coned_small_business_tou.json`. The Large Business structure is documented in `rates/coned_large_business_tou.json` for reference; see Limitations.

| Parameter | Value | Source |
|---|---|---|
| Summer peak, Jun 1 to Sep 30, Mon-Fri 8 a.m. to 10 p.m. | $0.5443/kWh | coned.com, Time-of-Use Rates, Small Business |
| Winter peak, all other months, same hours | $0.2680/kWh | same |
| Off-peak, all other hours | $0.0199/kWh | same |
| Monthly customer charge | $34.00 | same |
| Gas, default | $0.0387/kWh | EIA, New York commercial natural gas price, trailing 12-month average to May 2026, converted at 10.35 therm/Mcf and 29.3071 kWh/therm |

What the electricity default represents: Con Edison publishes these figures as the TOU alternative to its standard delivery rate. Supply is procured separately and passed through. The published rates exclude surcharges, taxes, and General Rule 30 adjustments. The component's electricity result is therefore a delivery-side estimate and will be lower than a bill. The gas default is an all-in statewide commercial average, so the two fuels are not on the same basis by default. Replace both with tariff values from the same source when the result matters.

Rates change. The JSON records carry a `retrieved` date. Re-check the source before reusing the defaults on a new project.

## Validation

Annual reconciliation. On two EnergyPlus runs of the same 128.83 m2 building (gas boiler, and all-electric VRF) the four TOU bucket totals sum to the annual kWh exactly, and the annual kWh matches the model's tabular End Uses total to the reported precision. The hourly cost collection sums to the annual cost to the cent.

Robustness matrix. v3.1 was run against twelve variants of the same load to confirm it either returns the identical answer or refuses with a clear message. Every conversion it applies is listed under Notes in the report, so nothing is silent.

| Input variant | Result |
|---|---|
| kWh, hourly, 8,760 values | baseline |
| Same load in J, or GJ | identical cost, unit conversion noted |
| Power in kW instead of energy | identical cost, converted per interval, noted |
| 15-minute timestep, 35,040 values | identical cost, summed to hourly, outputs hourly, noted |
| Leap-year run, 8,784 values | runs, Feb 29 priced, noted |
| A list of several collections on one input | summed, count noted |
| Partial run period | refused with the count it found and the count it expected |
| Monthly reporting frequency | refused, asks for hourly reporting |
| Gas collection of the wrong length | gas ignored, noted, electricity still priced |
| Hours with negative electricity (export) | priced at import rate, net metering flagged as not modelled |
| `start_day_of_week_` off by one day | about 2 percent cost shift on this load, which is why the input is exposed |

## Limitations

- Hourly resolution. Billing demand is usually metered on 15 or 30 minute intervals, so hourly-average peaks understate billing peaks. `demand_mult_` exists to correct for this, but the right value is load-specific. Values of 1.0 to 1.2 are typical; flat equipment-dominated loads sit near 1.0.
- Single-rate demand model. `demand_rate_` applies one $/kW to one monthly peak. Con Edison's Large Business TOU stacks three coincident-period demand charges. The component approximates that structure at best. Extend the script or use a dedicated tariff engine such as URDB-based tools for real large-service work.
- No holidays. Weekday holidays are priced as peak days. Con Edison's small business tariff text does not list holiday treatment on the rate page; check the tariff if it matters.
- No super-peak. The residential TOU rate has a 2 to 6 p.m. summer super-peak; this component has two periods only.
- Fixed 8,760 calendar. Leap-year runs and partial run periods fall back to the collection's own datetimes, but that path has had less testing.
- Ladybug Monthly Chart on hourly data. `ladybug-core` groups hours into months with an inclusive slice that carries the first hour of the next month into the current month (`group_by_month`, `_values[indx:indx + interval + 1]`). Monthly bars built from the hourly collection therefore read about one hour high per month, roughly 0.05 percent on a flat load. Use `monthly_file` when the monthly figures need to be exact.

## Notes on engines

Grasshopper in Rhino 8 runs three Python engines side by side: CPython 3 in the Python 3 component, a RhinoCode IronPython 2 engine in the same component's IronPython mode, and the older IronPython engine that every Ladybug Tools component uses. A Ladybug object created in one engine is opaque to the others. Passing a collection into the wrong engine shows up as `IronPython.NewTypes.System.Object_N$N` and failed `hasattr` checks; passing one out produces errors like `data_collections must contain data collections. Got MonthlyCollection`.

Version 2 avoids the problem entirely. Only floats, strings, and file paths cross the component boundary, all of which every engine handles identically. LB Deconstruct Data turns collections into floats on the way in, and LB Load Data turns the JSON files back into collections on the way out, inside the Ladybug engine where LB Hourly Plot and LB Monthly Chart expect them.

Version 1, in `legacy/`, built collections directly and only works when the script component shares an engine with LBT. It is kept for reference.

## Repository layout

```
src/tou_cost_v3_direct.py              v3, direct collections, IronPython components
src/tou_cost.py                        v2, JSON bridge, works in Python 3
legacy/tou_cost_ironpython_v1.py       v1, direct Ladybug objects, legacy GhPython only
rates/coned_small_business_tou.json    default rate record with source and date
rates/coned_large_business_tou.json    reference structure, partial support
docs/CHANGELOG.md
examples/                              drop a .gh, .ghuser, and screenshots here
```

## License

MIT. See LICENSE.

## Disclaimer

This is a modeling estimate, not a bill calculator. Rates are transcribed from public utility web pages on the dates recorded in `rates/` and may have changed. Confirm against the current tariff before making decisions on the output.
