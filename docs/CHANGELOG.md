# Changelog

## 3.1.0  (2026-08-31)

- Lists of collections are summed on either data input
- Unit conversion to kWh for J, kJ, MJ, GJ, Wh, MWh, Btu, kBtu, MMBtu, therm
- Power collections (W, kW, MW) converted to energy per interval
- Sub-hourly timesteps summed to hourly; output collections forced to hourly
- Leap-year runs (8,784 hours) supported
- Partial run periods, monthly data, and mismatched gas refused or ignored with a message instead of truncated
- Negative hours flagged
- Notes and Build log sections in the report list every conversion and fallback

## 3.0.0  (2026-08-31)

- `tou_cost_v3_direct.py`: collections in, collections out, no Deconstruct or Load Data. Builds outputs from the incoming object's own class instead of importing ladybug, so results pass LB components' isinstance checks from the IronPython 2 component as well as legacy GhPython.
- New `hourly_rate` output, the $/kWh rate in effect each hour, for plotting the tariff itself
- v2 retained for the Python 3 component

## 2.0.0  (2026-08-31)

- Engine-agnostic rewrite. Inputs are 8,760 floats from LB Deconstruct Data; outputs are floats plus two JSON files that LB Load Data turns into Ladybug collections. Runs in the Rhino 8 Python 3 component.
- New `hourly_file` output: hourly cost in USD and hourly rate in USD/kWh, ready for LB Hourly Plot and LB Monthly Chart
- New `monthly_file` output: monthly cost in USD and monthly peak in kW
- New `folder_` input for the JSON location
- Demand and fixed charges distributed across hours so hourly and annual totals agree
- v1 moved to `legacy/`

## 1.0.0  (2026-08-31)

First tagged version.

- Two-season, two-period TOU energy pricing on hourly data collections
- Optional gas at a flat rate
- Optional single-rate demand charge, fixed monthly charge, and demand multiplier
- Monthly cost and monthly peak kW emitted as Ladybug MonthlyCollections for LB Monthly Chart
- Peak timestamps as a separate list output
- `start_day_of_week_` accepts day names
- All rate inputs optional with Con Edison Small Business TOU defaults
- Goo-unwrapping so inputs survive Grasshopper wrappers

Known issues carried into 1.0.0 are listed under Limitations in README.md.
