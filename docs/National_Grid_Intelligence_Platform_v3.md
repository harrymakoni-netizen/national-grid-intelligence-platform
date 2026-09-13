
NATIONAL GRID

INTELLIGENCE PLATFORM


An AI System for Revenue Protection, Loss Detection and

Predictive Grid Maintenance in Zimbabwe

Development Proposal  —  Version 3.0

| Prepared by HJM Technologies September 2026 Proposed pilot counterparty: Zimbabwe Electricity Transmission and Distribution Company (ZETDC) Secondary stakeholders: ZESA Holdings, ZERA, industrial and mining customers |
| --- |


This is an internal development specification. It defines what will be built, in what order, with what resources, and how each component will be validated. No engagement with ZETDC has been concluded at the date of this version, and no representation of an existing relationship is made or implied.



Contents

1.   Executive Summary	3

2.   Problem Definition	4

3.   Design Constraint: Building for the Data That Exists	5

4.   Prior Art and the Build-versus-Buy Argument	6

5.   System Overview	7

6.   Layer 1 — The Grid Sensing Device	7

7.   Layer 3 — The Feeder Digital Twin	9

8.   Layer 4 — The Analytical Layer	10

9.   Extension and Research Modules	12

10.  Layer 5 — Closed-Loop Field Operations	14

11.  Layers 2 and 6 — Data Foundation and Presentation	15

12.  Development Without Utility Data	16

13.  Build Sequence	18

14.  Resourcing, Cost and Timeline	20

15.  Validation and Acceptance Criteria	21

16.  Legal, Regulatory and Data Protection	22

17.  Implementation Roadmap	23

18.  Commercial Model	24

19.  Risks and Mitigations	25

20.  Value Proposition	26

21.  Immediate Next Steps	26

Appendix A — Summary of Analytical Modules	27

Appendix B — Pilot Success Metrics	28

Appendix C — Development Resources	29


# 1.  Executive Summary

The National Grid Intelligence Platform is an AI system that gives an electricity utility a single, drillable view of its network — from the national balance sheet down to an individual prepaid meter — and uses machine learning to find the money and the failures that are currently invisible.

It addresses four losses that a distribution utility carries simultaneously: electricity that is delivered but never billed, electricity that is billed but never paid for, transformers that fail without warning, and industrial customers who waste power because nobody can see where it goes.

The design principle that separates this platform from conventional grid-analytics products is that it is built for the data ZETDC actually has, not the data a European distribution utility would have. Zimbabwe does not have wide-scale interval metering, and telemetry below 33 kV is sparse. Any system that requires those as preconditions cannot be piloted. This platform is therefore built on the single richest dataset the utility already owns and already digitises continuously — the prepaid vending transaction log — augmented by a small number of low-cost transformer monitors that can be assembled locally for well under two hundred United States dollars per unit.

That combination makes a real pilot possible within one quarter rather than one procurement cycle.

## 1.1  What the platform does

- Revenue protection — measures energy delivered into each distribution transformer against energy actually vended beneath it, and classifies the difference as technical loss, theft, meter failure, or self-generation.

- Predictive maintenance — models transformer health as a survival problem and forecasts remaining useful life from thermal, loading and power-quality signals, so failing units are replaced on schedule rather than after an outage.

- Load-shedding intelligence — forecasts feeder demand and generates equitable, criticality-weighted shedding schedules, then publishes them in a form the public and large customers can plan around.

- Distributed solar intelligence — detects and maps unregistered rooftop solar from consumption behaviour and imagery, and forecasts the resulting erosion of utility revenue.

- Industrial energy intelligence — disaggregates a plant’s total load into individual machines and processes without sub-metering every circuit, and identifies demand-charge and power-factor savings.

- Closed-loop field operations — dispatches inspectors from a prioritised queue, captures the outcome of every visit, and feeds that outcome back into the models as a training label.

## 1.2  The commercial position

Two revenue paths run in parallel, deliberately, so that neither depends on the other.

Path A — Industrial energy intelligence, sold now. Mines, tobacco processors, milling operations, hotels and hospitals pay maximum-demand tariffs, run expensive diesel generation, and have almost no visibility into their own consumption. The same hardware and the same platform, framed as cost reduction rather than loss detection, can be sold on a monthly subscription with no procurement cycle and no state approval. This funds the company and produces named reference sites.

Path B — Utility deployment, on a gain-share contract. Rather than asking a capital-constrained state utility to buy software, HJM Technologies funds the pilot and is compensated as a percentage of verified recovered revenue over a defined term. This removes the capital expenditure line entirely, transfers delivery risk to the vendor, and is a materially easier internal approval than a licence purchase.

The proposed entry point is a single 11 kV feeder, a ninety-day measurement window, and one headline number: recovered kilowatt-hours.

## 1.3  The defensible asset

The machine-learning techniques used here are published and available to anyone. The asset that cannot be copied is the labelled dataset produced by the closed field-operations loop. Every inspection that confirms a bypass, clears a household as a solar adopter, or identifies a failed meter becomes a labelled training example generated under Zimbabwean conditions — prepaid tariffs, load-shedding-distorted baselines, high informal-settlement density, and heavy behind-the-meter solar penetration. After two to three quarters of operation this dataset has no equivalent anywhere, and it is what turns a set of open-source models into a durable business.

## 1.4  What has changed in this version

Version 3.0 converts the document from a pitch into a build specification. The problem analysis, architecture and commercial model of Version 2.0 are retained substantially unchanged. The following are new:

- Section 4 — an assessment of prior art and an explicit build-versus-buy argument.

- Section 12 — a development track that proceeds to a demonstrable system with no utility data access whatsoever, which is the condition that will actually obtain for the first two quarters.

- Section 13 — a build sequence written for a very small team, with dependencies and a critical path.

- Section 14 — resourcing, indicative costs and a timeline.

- Section 15 — validation criteria defining what counts as each component working.

- Section 16 — an expanded treatment of data protection obligations under the Cyber and Data Protection Act.

- Appendix C — named public datasets and open-source libraries for cold-start development.

- The ten analytical modules of Version 2.0 are reorganised into four core modules and a deferred research track, because the original list is not buildable by a small team in a first release and presenting it as though it were undermines the credibility of the rest.

# 2.  Problem Definition

The challenges below are related but distinct, and are frequently conflated in utility reporting. Separating them is itself part of the value the platform delivers, because each requires a different operational response.

## 2.1  Non-technical loss

Energy is delivered into a distribution network and consumed without being paid for. The mechanisms include direct hooking onto low-voltage lines, meter bypass, tampering with prepaid meter internals, and reversal or cloning of vending credentials. Because there is no measurement between the substation and the customer, these losses are only discovered through physical audit, which is slow, expensive, and covers a small fraction of the network in any given year.

## 2.2  Technical loss mistaken for theft

Long, overloaded low-voltage feeders, undersized conductors and overloaded transformers all produce genuine physical losses. When the utility cannot compute the expected technical loss for a given feeder, every unexplained gap becomes a suspected theft, inspection resources are wasted on physically-explained losses, and network reinforcement that would actually solve the problem is never prioritised.

## 2.3  Unpredictable distribution asset failure

Distribution transformers fail from sustained overload, thermal ageing, insulation breakdown and moisture ingress. In nearly all cases the failure is preceded by measurable warning signs over weeks or months — rising operating temperature at a given load, increasing current imbalance across phases, growing harmonic distortion, and a rising frequency of protective operations. None of this is currently observed, because nothing is watching.

## 2.4  Vandalism and asset theft

Copper conductor, transformer oil and transformer cores are stolen for resale. The consequence is not only the replacement cost of the asset but an extended outage for every customer downstream, and in the case of oil theft, the destruction of a transformer that was otherwise serviceable. Detection today depends on a customer reporting the outage, which typically means hours of delay and no prospect of interception.

## 2.5  Behind-the-meter generation the utility cannot see

Sustained load shedding has driven rapid adoption of rooftop solar and battery storage by exactly the customer segment that contributes most to revenue. Much of this capacity is installed without registration. The immediate operational consequence is that consumption falls sharply for legitimate reasons, which corrupts any naive loss-detection logic. The strategic consequence is that the utility is losing its highest-value load without a quantified forecast of how fast, which makes tariff planning and network investment decisions unsound.

## 2.6  Industrial consumption without visibility

Large customers are billed on both energy and maximum demand, and frequently incur avoidable charges through poor power factor, uncoordinated plant start-up, and equipment left running at no load. Without process-level measurement, the plant manager receives a single monthly figure and has no basis on which to act.

## 2.7  Fragmented visibility

Vending data, billing records, outage logs, SCADA telemetry and maintenance records exist in separate systems with no shared identity for a physical asset. There is consequently no view in which a national loss figure can be decomposed downward to the substation, the transformer, and finally the meter responsible for it. This absence of a single hierarchical model of the network is the root constraint underneath every problem listed above.

# 3.  Design Constraint: Building for the Data That Exists

Most commercial grid-analytics platforms assume interval metering across the customer base and telemetry at every distribution substation. Under those assumptions the analytical problem is comparatively easy. Zimbabwe does not meet those assumptions, and a proposal that quietly requires them is not implementable.

The platform is therefore designed around three tiers of data, ordered by how readily they can actually be obtained.

## 3.1  Tier 1 — Data already held and already digital

- Prepaid vending transaction records. Every token purchase carries a timestamp, a meter identifier, a monetary value, a kilowatt-hour quantity, a tariff band and a vending channel. This is a continuous, national, per-customer dataset that already exists in a central system. It is the foundation of the platform.

- Customer and connection master data. Meter identifiers, account status, tariff category, premises address and — where recorded — the transformer or feeder the connection sits beneath.

- Post-paid billing and meter reading history for commercial and industrial accounts.

- Outage, fault and maintenance logs, including protective device operations and asset replacement records.

- Load-shedding schedules by group and feeder, which are required to correct consumption baselines.

## 3.2  Tier 2 — Data obtainable with modest new hardware

The measurement gap sits at the distribution transformer: the point where energy enters the low-voltage network. Installing a compact monitor at that point converts an unmeasurable inference problem into a straightforward energy-balance calculation. Section 6 specifies this device.

## 3.3  Tier 3 — Data available in principle, treated as optional enrichment

- SCADA and energy-management telemetry at transmission and primary distribution voltages.

- Meteorological and solar irradiance data, obtainable free from open satellite reanalysis products.

- Satellite and aerial imagery for rooftop solar detection and network asset verification.

- Geographic information system records of network topology, where they exist and are current.

The platform must degrade gracefully. Every analytical module is specified to produce a useful, honestly-caveated output using Tier 1 data alone, and to increase in confidence as Tier 2 and Tier 3 data become available. This is a design requirement, not an aspiration.

# 4.  Prior Art and the Build-versus-Buy Argument

Grid analytics is not an empty field, and any serious technical evaluator will ask why an existing product is not being purchased instead. The question deserves a direct answer rather than an assertion of novelty.

## 4.1  What already exists

| Category | Representative capability | Why it does not resolve this problem |
| --- | --- | --- |
| Meter data management platforms | Validation, estimation and editing of interval meter reads; billing determinants; loss reporting | Presupposes interval metering across the customer base. With prepaid token vending as the dominant record, there is no interval stream to manage. |
| Utility analytics suites | Loss analytics, asset analytics and outage management layered on an existing enterprise data warehouse | Licence and implementation cost is denominated in a currency of scale this utility does not have, and integration assumes systems that are not present or not connected. |
| Distribution sensing vendors | Instrumentation at the distribution transformer with associated analytics | Per-unit device cost is typically one to two orders of magnitude above the bill of materials in Section 6.2, which makes feeder-level density uneconomic. |
| Open-source power system tools | Power-flow computation, network modelling, state estimation | These are components, not a system. They are used here rather than competed with. |
| Published theft-detection research | Classification of theft from interval consumption data, with strong reported accuracy | Almost universally assumes interval data and labelled theft cases. Neither is available at the outset here. |


Figures describing commercial products are indicative of category rather than specific quotations, and should be confirmed by direct enquiry before being represented externally.

## 4.2  The gap that justifies building

The unoccupied position is a system that performs loss attribution from prepaid vending events rather than interval reads, on a network instrumented at a cost that permits feeder-level coverage, with a field loop that manufactures its own training labels.

Each of those three choices is a response to a Zimbabwean constraint, and together they define a product that no incumbent is motivated to build, because the constraint does not exist in the markets those incumbents serve. That is the entire strategic basis of this platform, and it should be stated in exactly those terms to any technical evaluator.

## 4.3  What is genuinely novel, and what is not

Precision here protects credibility. The following are established practice and are used, not claimed:

- Survival analysis for asset remaining-life estimation.

- Gradient-boosted regression for demand forecasting.

- Sequence-to-point convolutional networks for load disaggregation.

- Segmentation networks for rooftop solar detection from imagery.

- Power-flow computation for expected technical loss.

The following are, to the best of current knowledge, either unaddressed or thinly addressed in the published literature, and constitute the platform’s technical contribution:

- Reconstruction of a continuous consumption profile from discrete prepaid token purchase events, with quantified uncertainty.

- Discrimination between unregistered solar adoption and meter bypass in a market where both are simultaneously prevalent and where load-shedding distorts every baseline.

- State inference across a sparsely instrumented distribution network using the network graph, addressed in Section 9.5 as a deferred research track.

# 5.  System Overview

The platform is a single system organised in six layers. Each layer is independently useful, and each one increases the value of the layers above it.

| Layer | Name | Function |
| --- | --- | --- |
| Layer 1 | Grid Sensing | Low-cost transformer and feeder monitors reporting energy, current, voltage, power quality and temperature over cellular networks. |
| Layer 2 | Data Foundation | Ingestion, cleaning and identity resolution across vending, billing, outage and sensor data, resolved onto a single hierarchical model of the network. |
| Layer 3 | Feeder Digital Twin | A physical model of each feeder that computes expected technical loss from network parameters and load, so that the residual can be attributed to non-technical causes. |
| Layer 4 | AI and Analytics | Consumption reconstruction, loss attribution, theft and solar discrimination, asset health and remaining-life estimation, demand forecasting and load disaggregation. |
| Layer 5 | Operations | Case management, inspector dispatch, evidence capture, outcome recording and the label feedback loop. |
| Layer 6 | Presentation | Hierarchical dashboard with drill-down from national aggregate to individual meter, alerting, natural-language query and automated regulatory reporting. |


## 5.1  The hierarchical model of the network

Every measurement, every customer and every asset in the system is tagged with its position in a single tree that mirrors the physical network:

- National system — generation and transmission balance

- Region and primary substation — 330 kV and 132 kV

- Distribution substation — 33 kV and 11 kV

- Distribution transformer — the neighbourhood, the plant, the street

- Low-voltage feeder and line section

- Individual connection — household, business, industrial customer

This tagging is what makes drill-down possible: the national figure is not a separate number, it is the aggregation of every node beneath it, and an operator can therefore descend from an unexplained national loss to the specific transformer producing it. Establishing this hierarchy — in particular, correctly associating every meter with the transformer that feeds it — is the single most important data-engineering task in the project, and Section 11.1 addresses the fact that this association is often missing or wrong in utility records.

# 6.  Layer 1 — The Grid Sensing Device

Purpose-built commercial distribution-transformer monitors are typically priced in the low thousands of United States dollars per unit, which places any meaningful deployment out of reach. A device sufficient for this application can be built from commodity components at a small fraction of that cost, and can be assembled locally.

## 6.1  Measurement requirements

- Three-phase current and voltage, sampled fast enough to compute true RMS values and total harmonic distortion.

- Real and apparent energy accumulated per phase, reported at fifteen-minute resolution.

- Power factor and phase imbalance.

- Transformer tank or oil temperature, and ambient temperature for reference.

- Supply presence and interruption events, timestamped, with sufficient reserve power to report the loss of supply before shutting down.

- Enclosure tamper detection and accelerometer-based disturbance sensing, for vandalism alerting.

## 6.2  Indicative bill of materials

| Component | Function | Indicative unit cost |
| --- | --- | --- |
| ESP32 or STM32 microcontroller | Sampling, local processing, buffering and communications control | USD 5 – 12 |
| Three-phase energy metering front-end IC | Hardware computation of RMS values, power, energy and harmonic content | USD 8 – 15 |
| Split-core current transformers (×3) | Non-invasive current measurement, no supply interruption to install | USD 18 – 36 |
| Voltage sensing transformers or divider network | Phase voltage measurement with isolation | USD 6 – 12 |
| Digital temperature probes (×2) | Tank or oil temperature and ambient reference | USD 3 – 6 |
| LTE Cat-M1 or 2G/3G cellular module with SIM | Data backhaul over existing mobile networks | USD 12 – 25 |
| Supercapacitor or small lithium cell with charge circuit | Last-gasp outage reporting and clock retention | USD 4 – 8 |
| IP65 enclosure, DIN mounting, glands, surge protection | Environmental protection and installation hardware | USD 20 – 40 |
| Assembly, calibration, testing and firmware | Locally performed | USD 15 – 30 |
| Indicative total per unit | Excluding installation labour and recurring data costs | USD 90 – 185 |


Costs above are planning estimates for budgeting purposes and must be confirmed against current supplier quotations before commitment. The relevant point is the order of magnitude: instrumenting an entire feeder is a capital cost measured in low thousands of dollars, not hundreds of thousands, which is what makes a self-funded pilot viable.

## 6.3  Communications and resilience

Devices report over MQTT to the platform ingestion service, buffering locally when connectivity is unavailable and back-filling on reconnection. Because load shedding regularly removes supply from exactly the assets being monitored, the device must distinguish a scheduled outage from an unplanned one by reference to the published shedding schedule, and must be able to transmit a final message on loss of supply. Devices are individually keyed, and all traffic is transport-encrypted; readings are signed at source so that a measurement used as evidence in a disconnection or prosecution can be shown not to have been altered in transit.

## 6.4  Vandalism detection

A transformer that goes dead outside a scheduled shedding window, with a preceding disturbance signature on the accelerometer and an enclosure tamper event, is a distinctive pattern that can be alerted within minutes. This capability alone has been sufficient in comparable deployments elsewhere to justify the monitoring hardware, independently of any revenue-protection benefit, and it should be presented as a standalone value proposition during the pilot.

## 6.5  Certification and installation constraint

A device installed on utility assets is subject to the utility’s own standards for equipment connected to its network, and installation on energised plant may only be performed by appropriately qualified personnel. Split-core current transformers are chosen specifically because they can be fitted without breaking the circuit, which materially reduces the approval burden, but it does not eliminate it. Confirmation of the applicable standard and of who may perform installation must be obtained during pilot negotiation and before any hardware is committed to production. This is a live constraint on the schedule in Section 14 and is not treated as a formality.

# 7.  Layer 3 — The Feeder Digital Twin

The central analytical claim of this platform is that it can separate technical from non-technical loss. That claim cannot be honoured by statistical anomaly detection alone. An anomaly detector can establish that a pattern is unusual; it cannot establish that the energy went into conductor heating rather than into an illegal connection. Making the distinction credible to a utility engineer requires a physical model.

## 7.1  What the twin contains

- Network topology: the connectivity of substations, feeders, line sections, transformers and connections.

- Conductor parameters: type, cross-sectional area, length and resulting impedance per section.

- Transformer parameters: rating, impedance, no-load and load losses, tap position and vector group.

- Connection points: customer connections with their measured or estimated load profiles.

## 7.2  How it is used

For each interval, the load at every connection point is estimated from vending-derived consumption and a power-flow solution is computed across the feeder. This yields the expected technical loss for that feeder under that specific loading condition, including its dependence on load magnitude, phase imbalance and ambient temperature. The unexplained residual is calculated as follows:

| Non-technical loss  =  Energy measured into the transformer  −  Energy accounted to customers  −  Modelled technical loss |
| --- |


The output of the physical model becomes an input feature to the machine-learning layer rather than a competitor to it. This is a physics-informed architecture, and it produces three benefits: the models require far less training data because the physically-explained variance is already removed; the outputs are explainable to engineers in terms they accept; and the same model identifies feeders where the correct intervention is reconductoring or transformer replacement rather than an inspection visit.

## 7.3  Implementation and cold start

The twin is implemented using established open-source power-system analysis libraries — pandapower for network modelling and balanced power flow, with OpenDSS accessed through its Python interface where unbalanced three-phase analysis of the low-voltage network is required. Both provide standard component models and solvers and remove any need to build power-flow computation from scratch.

Complete network records are unlikely to be available at the outset. The pilot therefore begins by surveying one feeder physically — walking the route, recording conductor types and spans, and capturing transformer nameplate data — which is a matter of days for a single feeder and produces a model of a quality that no records-based approach would achieve. Where parameters remain uncertain, they are estimated from measured behaviour by fitting the model to observed losses during periods in which non-technical loss can be reasonably assumed to be stable.

# 8.  Layer 4 — The Analytical Layer

Version 2.0 of this document specified ten analytical modules. That list describes the platform at maturity, and presenting it as a first release would be inaccurate. This version separates four core modules, which constitute the minimum system capable of producing a recovered-kilowatt-hour figure, from an extension set that follows once the core is operating and a deferred research track that should not be attempted until the platform has real labelled data.

| Tier | Modules | Rationale |
| --- | --- | --- |
| Core — first release | A Consumption reconstruction; B Loss attribution; C Asset health; D Demand forecasting | Together these produce the pilot headline number and the maintenance prioritisation that justifies the sensing hardware independently. |
| Extension — after core is operating | E Shedding allocation; F Solar intelligence; G Industrial load disaggregation | Each is valuable and each is buildable, but none is required for the pilot to report a result. G is built first among these, because it is the Path A commercial product. |
| Deferred research | H Graph inference over sparse instrumentation; I Inspection vision; J Operator language interface | H is a genuine research contribution and should be pursued as such, not promised as a delivery. I and J are low-risk but add nothing until the field loop and the data volume exist. |


## 8.1  Module A — Consumption Reconstruction from Prepaid Vending Events

### The problem

A token purchase records that a customer bought a quantity of energy at a moment in time. It does not record when that energy was consumed. A household may purchase weekly, fortnightly or erratically; purchase timing reflects income cycles, not load. Almost the entire published literature on metering analytics assumes interval consumption data, so this problem is largely unaddressed — and solving it is the precondition for every other module operating on Tier 1 data.

### Approach

The underlying consumption process is treated as a latent variable to be inferred from observed purchase events. Cumulative purchases over time provide a hard upper bound on cumulative consumption, and the intervals between purchases carry information about depletion rate. A state-space formulation, or equivalently a sequence model trained to predict the timing and size of the next purchase, produces a posterior estimate of consumption rate with quantified uncertainty. The estimate is conditioned on tariff band, connection type, settlement typology, season, temperature and the load-shedding hours applicable to the customer’s group.

Where a subset of connections has genuine interval metering — typically commercial and industrial customers — those records are used as ground truth to calibrate and validate the reconstruction for comparable customer classes.

### Output and evaluation

An estimated consumption profile per connection with confidence intervals, aggregable to transformer level. Evaluated on held-out interval-metered customers by mean absolute error at daily and monthly resolution, and by calibration of the predicted uncertainty. The aggregate estimate at transformer level is the operationally important quantity and is materially more accurate than any individual customer estimate, because errors are largely independent across customers.

## 8.2  Module B — Loss Attribution and the Theft-versus-Solar Problem

### The problem

This is the hardest and the most valuable model in the platform. A connection whose consumption falls by seventy per cent may have installed solar, may have been bypassed, may have a failed meter, may have been vacated, or may simply have become poorer. In aggregate these are indistinguishable. Confusing them is not a minor inconvenience: sending an inspector to accuse a lawfully self-generating household of theft destroys the utility’s standing with its customers and the platform’s standing with the utility.

### Discriminating signatures

| Cause | Characteristic signature |
| --- | --- |
| Rooftop solar | Gradual onset over days; reduction concentrated in daylight hours; strong correlation with satellite irradiance and cloud cover; pronounced seasonality; evening consumption largely preserved unless storage is present. |
| Battery storage added | Evening consumption also falls; recharging may create a distinctive post-restoration demand spike after shedding windows. |
| Meter bypass or tampering | Step change with no weather correlation; frequently partial, as a fraction of load is diverted; transformer-level load unchanged; often clustered among neighbouring connections. |
| Meter failure | Abrupt fall to near zero; no corresponding change in transformer loading; no seasonality; typically isolated to a single connection. |
| Vacancy or disconnection | Fall to zero with cessation of purchasing activity and, in most cases, a corresponding record in customer systems. |
| Genuine demand reduction | Proportional reduction preserving load shape; consistent with tariff changes or economic conditions across a wide population. |


### Approach

The problem is framed as multi-class time-series classification over daily and weekly load-shape descriptors, with the physically-modelled expected technical loss and the neighbourhood peer-group behaviour supplied as features. Because labels do not exist at the outset, training proceeds in three stages:

- Unsupervised stage. Autoencoder reconstruction error and isolation-forest scoring identify connections whose behaviour departs from their peer group, using no labels at all. Outputs at this stage are ranked suspicion scores, not classifications, and are presented as such.

- Weak-supervision stage. Labelling functions encoding domain rules — irradiance correlation implies solar; sustained zero consumption with an active transformer implies meter failure or bypass — are combined into probabilistic labels, and confirmed historical audit results are incorporated where the utility holds them.

- Supervised stage. Once the field operations loop has returned several hundred confirmed outcomes, gradient-boosted decision trees are trained on real labels and progressively replace the earlier stages. The models are retrained on a rolling basis as new outcomes arrive.

### Output and evaluation

A ranked case queue with a predicted cause, a confidence score, an estimated recoverable energy quantity, and the evidence supporting the classification. The operative metric is precision at the top of the ranked list — the proportion of dispatched inspections that find what the model predicted — because inspector capacity is the binding constraint. A secondary metric is recovered kilowatt-hours per inspection. Recall is reported but is deliberately not optimised in early phases, since a small number of high-confidence, correctly-diagnosed cases builds far more institutional trust than a large number of speculative ones.

## 8.3  Module C — Transformer Health and Remaining Useful Life

Asset failure is modelled as a time-to-event problem rather than a classification, because the data is right-censored: the great majority of monitored transformers have not failed, and treating them as negative examples discards the information that they have survived for a known duration. Gradient-boosted survival models, or a recurrent network trained with a survival objective, estimate a hazard function per asset from which remaining useful life and failure probability over a chosen horizon are derived.

### Inputs

- Loading history relative to nameplate rating, including the duration and severity of overload excursions.

- Thermal behaviour, specifically the relationship between operating temperature, load and ambient conditions, and the degradation of that relationship over time.

- Total harmonic distortion trend, as an indicator of insulation and winding condition.

- Phase current imbalance, which produces disproportionate heating and accelerates ageing.

- Frequency of protective operations and recorded fault events on the associated feeder.

- Asset age, manufacturer, rating and maintenance history where recorded.

### Cold start and evaluation

Historical failure records permit an initial model on age, rating and loading proxies before any sensors are installed. Physics-based thermal ageing models — the loading guides for oil-immersed transformers provide a standard relationship between hot-spot temperature and insulation life — supply a defensible prior, which is used to constrain the learned model until sufficient observed failures accumulate. Evaluation uses the concordance index for ranking quality and calibration of predicted failure probability against observed outcomes. The practical target is that assets flagged in the highest risk decile fail at a materially higher rate than the population, which is sufficient to reallocate a maintenance budget rationally.

## 8.4  Module D — Demand Forecasting

Feeder-level and system-level demand forecasts at day-ahead and week-ahead horizons, produced by gradient-boosted regression over lagged demand, calendar features, temperature, and load-shedding history, with quantile outputs so that uncertainty is explicit. Sequence models are appropriate where longer-horizon dependencies justify the additional complexity, but the boosted-tree baseline is strong and should be established first.

Forecast quality is measured by mean absolute percentage error at each horizon and by the calibration of the quantile bands. The forecast is a genuine machine-learning product; the shedding schedule that consumes it is not, and Section 9.1 is explicit about that distinction.

# 9.  Extension and Research Modules

## 9.1  Module E — Load-Shedding Intelligence

Given a demand forecast and an available-generation figure, the shedding requirement is determined and allocated across feeders. The allocation itself is a constrained optimisation problem, not a learning problem, and is solved as a mixed-integer program balancing several objectives:

- Protection of critical load — hospitals and clinics, water treatment and pumping, telecommunications infrastructure, and designated strategic industry.

- Equity of cumulative outage hours across residential groups over a rolling window, so that the same suburbs are not repeatedly disadvantaged.

- Avoidance of shedding on feeders with transformers already identified as thermally stressed, since repeated restoration inrush accelerates their failure.

- Preservation of revenue-generating load where doing so does not conflict with the objectives above.

- Operational feasibility — respecting switching constraints and minimum block durations.

The learning contribution is upstream, in the forecast, and downstream, in predicting which feeders will actually shed successfully and how post-restoration demand will behave. Presenting the optimiser itself as artificial intelligence would be inaccurate and would be identified as such by any competent engineer reviewing the proposal.

The module also publishes schedules through an application programming interface and a public-facing channel, in a machine-readable form that customers and large consumers can plan around. Accurate, dependable schedule publication is among the most visible improvements the platform can deliver and generates public and political support for the wider programme.

## 9.2  Module F — Distributed Solar Intelligence

Two independent estimation methods are used and reconciled against each other. The first infers installed capacity from consumption behaviour: the daylight-hours reduction, corrected for irradiance and adjusted for the customer’s prior load shape, implies a generation capacity. The second detects installations directly from aerial or satellite imagery using a segmentation network, an approach well established in the published literature, producing an independent capacity estimate from panel area and orientation.

Agreement between the two methods substantially raises confidence in both; disagreement identifies cases warranting investigation. The reconciled output supports three purposes: correcting the loss-attribution models so that self-generating customers are not pursued as theft cases; providing the utility and the regulator with a quantified map of installed distributed capacity that does not currently exist; and forecasting revenue erosion under adoption scenarios over a three-to-five-year horizon, which is directly relevant to tariff design and network investment planning.

## 9.3  Module G — Non-Intrusive Load Monitoring for Industrial Customers

Disaggregation of a plant’s aggregate demand into constituent machines and processes without metering every circuit. Sequence-to-point convolutional architectures are the established approach and perform well on the large, electrically distinctive loads found in industrial settings — motor drives, compressors, furnaces, chillers, pumps and conveyors.

Commissioning at each site involves a short supervised period in which known loads are switched under observation, which produces site-specific training data and substantially improves accuracy relative to a generic model. The outputs are directly actionable: energy and cost attributed to each process, identification of equipment operating at no load, quantified opportunity in power-factor correction and load scheduling to reduce maximum demand charges, and detection of developing mechanical faults from changes in a machine’s electrical signature.

Build priority: although classified as an extension module, this is the first extension to be built, because it is the product sold under Path A and therefore the component that funds the rest of the programme. Section 13 sequences it accordingly.

## 9.4  Modules I and J — Inspection Vision and Operator Language Interface

Optical character recognition of meter displays and serial numbers from inspector photographs; detection of physical tampering indicators as an assistive check supporting the inspector’s own judgement; verification that an inspection photograph was captured at the location and premises recorded; and rooftop solar detection from imagery as described in Module F.

A language model layer over the platform’s data provides natural-language querying of the network, plain-language explanation of why a specific connection was flagged, automated drafting of regulatory submissions with every number traceable to source, assembly of evidence packs into a coherent narrative, and translation of field instructions and customer notices into Shona and Ndebele. This layer is explicitly constrained to operate over retrieved platform data and is never permitted to originate a figure. Every quantitative statement it produces must resolve to a stored measurement, and the interface displays that provenance.

Both are low-risk to implement and add little until the field loop is generating volume. They are scheduled after the pilot reports.

## 9.5  Module H — Graph Inference over a Sparsely Instrumented Network

It will never be economic to instrument every node. The electrical network is, however, a graph, and the relationships between adjacent nodes are governed by known physical laws. A graph neural network operating over the network topology can propagate information from instrumented nodes to uninstrumented ones, producing state estimates across a whole feeder from a modest number of physical sensors.

The same architecture supports anomaly detection at the network level rather than the connection level, because a loss confined to a single node and a loss distributed across every node beneath a common point are topologically distinguishable — which is precisely the difference between theft and a faulty line section.

This module is deliberately deferred. It is the most technically ambitious component of the platform and a legitimate research contribution suitable for academic publication. It is also the component most likely to consume months without producing an operational result, and it cannot be properly evaluated until the digital twin and a real instrumented feeder exist to generate training data. It should be pursued as a research track alongside the commercial programme — ideally in collaboration with a university engineering faculty — and must not appear in any pilot commitment.

## 9.6  Where machine learning is deliberately not used

Credibility with the utility’s engineering function depends on being precise about this. Energy balance is arithmetic. Expected technical loss is a power-flow computation. The shedding allocation is constrained optimisation. Threshold alarms — a transformer exceeding a temperature limit, a voltage outside statutory bounds — are threshold alarms. Presenting any of these as artificial intelligence would be inaccurate, would be recognised immediately, and would cast doubt on the modules where the machine-learning contribution is genuine and substantial.

# 10.  Layer 5 — Closed-Loop Field Operations

Detection without dispatch is a report that nobody acts on. The operations layer is what converts model output into recovered revenue, and simultaneously produces the labelled data that improves the models. It is the component most often absent from analytics proposals and the one that determines whether the platform delivers measurable value.

## 10.1  The loop

1.  The model produces a ranked case queue with predicted cause, confidence, estimated recoverable energy and supporting evidence.

2.  Cases are assigned to inspectors and sequenced geographically to minimise travel.

3.  The inspector attends with the full case context available offline on a mobile device, including consumption history, the transformer’s recent behaviour and comparison against neighbouring connections.

4.  Findings are captured on site: photographs, geographic position, meter reading and serial number, seal condition, and a structured outcome classification.

5.  The outcome is recorded — confirmed tampering, confirmed bypass, meter failure, lawful self-generation, vacant premises, no fault found — together with any corrective action taken.

6.  The outcome becomes a labelled training example. The models retrain on a rolling basis, and precision at the top of the queue improves measurably with each cycle.

## 10.2  Design requirements

- Full offline capability, with reliable synchronisation on reconnection. Coverage cannot be assumed in the areas where inspection is most needed.

- Structured outcome capture with no free-text-only path, because unstructured findings cannot be used as training labels.

- Mandatory recording of negative outcomes. A case that finds nothing is as valuable to the models as one that finds tampering, and inspector workflows must not permit it to go unrecorded.

- Tamper-evident capture, with photographs bound to location, time and device identity at the point of capture.

- Inspector safety features, including check-in and duress signalling, given that revenue-protection visits can be confrontational.

## 10.3  Evidence and due process

A theft finding leads to disconnection, back-billing and in some cases prosecution, and each of those may be challenged. The platform must therefore produce an evidence pack meeting an evidentiary standard: source-signed transformer measurements over the relevant period, the connection’s consumption and vending history, the modelled technical loss demonstrating that the shortfall is not physically explained, the peer-group comparison, dated field photographs with verified location, the inspector’s structured findings, and a complete audit trail of every person who accessed or altered the case record.

A system that produces defensible evidence is worth considerably more than one that produces an alert, and building to this standard from the outset costs very little more than building without it.

## 10.4  Internal integrity

Revenue loss in utilities frequently involves internal participation — irregular vending activity, unauthorised account adjustments, inspections recorded as completed that did not occur, and repeated clearance of the same connection by the same officer. The same anomaly-detection machinery applies to internal transaction and workflow data. This capability must be introduced carefully and with executive sponsorship, since it is organisationally sensitive; it should not be led with in early engagement, but it is a material part of the platform’s long-term value and should be designed for from the beginning.

# 11.  Layers 2 and 6 — Data Foundation and Presentation

## 11.1  The connection-to-transformer association problem

The entire hierarchical model depends on knowing which transformer feeds which connection. In practice this association is frequently missing, outdated or incorrect in utility records, and it cannot be assumed. Three complementary methods are used to establish and continuously verify it:

- Existing records and geographic information system data as the starting point, treated as a hypothesis rather than fact.

- Correlation-based inference: connections fed by the same transformer share outage timing, voltage disturbance signatures and shedding windows, which allows the association to be inferred statistically from behaviour and existing records to be corrected where they are wrong.

- Field confirmation during installation and inspection visits, which progressively converts inferred associations into verified ones.

Correcting this association is itself a deliverable of real standing value to the utility, independent of any analytical output, and should be presented as such.

## 11.2  Architecture

| Component | Approach |
| --- | --- |
| Ingestion | MQTT for device telemetry; scheduled and streaming interfaces for vending, billing and outage systems; file-based transfer supported where system integration is not initially permitted. |
| Storage | Time-series database for measurements and device telemetry; relational database for network hierarchy, customer records, cases and outcomes; object storage for imagery and evidence. |
| Processing | Stream processing for real-time alerting; scheduled batch processing for reconstruction, loss attribution and model scoring. |
| Modelling | Python analytical stack with versioned models, tracked experiments, reproducible training pipelines and automated monitoring for data and concept drift. |
| Physical modelling | pandapower and OpenDSS providing component models and power-flow solvers for the feeder digital twin. |
| Application | Web application with a role-based hierarchical interface, and an offline-capable mobile application for field operations. |
| Deployment | Containerised services deployable to utility-hosted infrastructure or to cloud, since data-residency requirements for a state utility cannot be assumed to permit external hosting. |


## 11.3  Hierarchical operational view

A single interface in which the national loss figure decomposes downward through region, primary substation, distribution substation, transformer and connection, with geographic and schematic representations at each level. Every figure at every level is traceable to the measurements that produced it, and every anomaly can be opened to reveal the evidence behind it.

## 11.4  Role-specific views

| Role | Primary view |
| --- | --- |
| Executive management | National loss trend, recovered revenue against target, asset risk exposure, distributed generation penetration and forecast revenue erosion. |
| Revenue protection | Case queue, inspector productivity, recovery per inspection, precision trend by cause category, and geographic concentration of confirmed cases. |
| Network operations | Asset health rankings, remaining-life estimates, thermal and loading alarms, outage and vandalism alerts, and maintenance prioritisation. |
| System control | Demand forecast, generation availability, shedding requirement and the proposed allocation with its justification. |
| Regulatory and compliance | Automatically generated reliability and loss reporting with full traceability to source measurements. |
| Industrial customer | A separate tenant view showing process-level consumption, demand-charge exposure, power-factor position and identified savings. |


## 11.5  Regulatory reporting

Reliability indices, loss reporting and other periodic regulatory submissions are generated directly from platform data rather than assembled manually. This is deliberately positioned: it makes the platform the system of record for figures the utility is obliged to produce, which is both operationally valuable to the utility and strategically valuable in establishing the platform’s permanence. It also creates a legitimate secondary relationship with the regulator, which is useful in securing the initial engagement.

## 11.6  Multi-utility portability

Network hierarchy depth, tariff structures, currency handling, vending record formats and regulatory reporting templates are implemented as configuration rather than embedded in code. The loss profile and prepaid-metering model addressed here are common across the region, and portability designed in from the outset is what allows a successful Zimbabwean deployment to become a regional product rather than a single contract. Multi-currency handling is a specific requirement given local billing practice, and must be present in the data model from the first version rather than retrofitted.

# 12.  Development Without Utility Data

This is the section Version 2.0 lacked, and it governs the first two quarters of work.

The platform is designed around ZETDC’s vending data, and that data will not be available for some months and may never be available on the terms first requested. A development plan that waits for it produces nothing. A development plan that quietly assumes it produces a system that fails on contact with reality.

The operating principle is therefore: build and validate every component against synthetic and public data first, so that capability is demonstrable before access is requested. A utility is far more likely to grant a narrow historical data extract to a party that can show a working system than to one that can show a proposal.

## 12.1  The synthetic vending generator

The first artefact built is not a model. It is a generator that produces a synthetic Zimbabwean distribution network and its associated prepaid vending history, with ground truth known by construction.

The generator must produce, for a configurable feeder:

- A network topology with transformers, low-voltage feeders and connections, with realistic conductor lengths and ratings.

- Per-connection true consumption profiles differentiated by customer archetype — low-income high-density, medium-density residential, small commercial, industrial — with diurnal, weekly and seasonal structure.

- Load-shedding windows applied to the true consumption, since every real baseline is distorted by them and a model trained without this distortion will not transfer.

- Prepaid purchase events generated from the true consumption by a plausible purchasing behaviour model, with income-cycle clustering, variable purchase sizes and erratic timing.

- Injected ground-truth anomalies at known connections and known times: partial bypass, full bypass, meter failure, vacancy, and solar adoption with a specified capacity and irradiance response.

- Technical losses computed physically from the network model rather than imposed as a fixed percentage.

Because the true consumption, the true losses and the true anomaly labels are all known by construction, every downstream model can be evaluated properly from day one. This is the closest thing to a laboratory that this project will have before a real feeder exists, and the quality of the entire programme depends on the fidelity of this generator.

| The generator is the single most important early deliverable and the most commonly skipped. Without it, Module A cannot be evaluated, Module B has no labels, the digital twin cannot be tested, and the dashboard has nothing to display. It should be built before anything else and treated as production code, not as a throwaway script. |
| --- |


## 12.2  Public datasets that substitute for what is missing

Synthetic data validates mechanics but cannot validate realism. Public datasets supply behavioural realism for the components where it matters most. The specific sources are listed in Appendix C; the roles they play are as follows:

| Development need | Substitute source |
| --- | --- |
| Realistic residential and small-commercial load shapes, to drive the synthetic generator rather than inventing profiles | Public half-hourly smart-meter trial datasets, converted into synthetic prepaid purchase sequences by simulating token depletion against the known consumption. |
| Ground truth for consumption reconstruction | The same datasets, held out. Because true interval consumption is known, reconstruction error is directly measurable. |
| Labelled theft behaviour | Published electricity-theft detection datasets with real labelled cases, used to develop and benchmark the classifier architecture before Zimbabwean labels exist. |
| Solar generation signatures against irradiance | Public solar-home datasets containing gross generation and consumption separately, which is exactly the decomposition the solar module must infer. |
| Irradiance and weather | Open satellite reanalysis products, free at the point of use, which will also be the production source. |
| Industrial load disaggregation | Published non-intrusive load monitoring datasets for architecture development, with site-specific commissioning data collected at the first real customer. |


Every one of these is public, free, and available immediately. The distributions differ from Zimbabwean conditions in ways that matter — none of them carries load shedding, prepaid purchasing or informal-settlement density — and that gap is precisely what the synthetic generator exists to bridge. Models are developed on public data for architecture and benchmarking, then re-trained and re-evaluated on synthetic Zimbabwean conditions before any claim is made.

## 12.3  Hardware development in parallel

The sensing device has no dependency on utility data and can be developed to a finished, bench-validated state during the same period. Development proceeds on a controlled test rig: a known three-phase load, a reference instrument for calibration, and deliberately introduced conditions — phase imbalance, harmonic injection, supply interruption, enclosure disturbance — to verify that the device measures and reports what it claims to.

A device that has been calibrated against a reference instrument and can demonstrate its accuracy is a materially different proposition in a pilot negotiation than a prototype on a bench. This work should be complete before ZETDC is approached.

## 12.4  What can be demonstrated with no utility involvement

At the end of the pre-access period the following should exist and be demonstrable to any visitor within twenty minutes:

- A physical sensing device measuring a real load on a bench, reporting live into the platform.

- A synthetic feeder rendered in the drill-down interface, from national aggregate down to individual connection.

- A simulated theft event injected at a known connection, detected by the platform, correctly classified, and presented as a case with its supporting evidence.

- A simulated solar adoption at another connection, correctly distinguished from the theft case rather than flagged alongside it.

- A transformer degradation trajectory detected and flagged ahead of the simulated failure.

- Measured reconstruction error against held-out real interval data, stated as a number.

That demonstration is the asset that opens the utility conversation, and it is achievable entirely without them.

# 13.  Build Sequence

This section assumes a very small team — in the first instance one full-time technical founder using AI-assisted development tooling, with specialist input bought in for specific tasks. Sequencing therefore matters far more than it would with a larger team, because there is no parallelism to absorb a wrong ordering.

## 13.1  Dependency order

The following ordering is imposed by dependencies, not by preference. Each item requires everything above it.

| # | Component | Why it sits here |
| --- | --- | --- |
| 1 | Network hierarchy data model | Every measurement, customer, asset and case is tagged to it. Nothing can be stored coherently until it exists, and retrofitting it is a rebuild. |
| 2 | Synthetic vending and network generator | Produces the data that every subsequent component is developed and evaluated against. |
| 3 | Ingestion and time-series storage | Required before either synthetic or device data can accumulate. |
| 4 | Feeder digital twin | Produces modelled technical loss, which is a required input feature to loss attribution. Building attribution first means building it twice. |
| 5 | Module A — consumption reconstruction | Converts vending events into the consumption estimates that attribution consumes. |
| 6 | Sensing device, bench-validated | Supplies the measured energy term in the loss equation. Development runs in parallel from the start but must complete before a feeder pilot. |
| 7 | Module B — loss attribution | Requires 4, 5 and 6. This is the core of the platform and should not be started early. |
| 8 | Drill-down interface | Requires a hierarchy and something to display. Built early enough to shape the data model, completed after attribution. |
| 9 | Field operations application | Requires a case queue from 7. Without it, no labels are generated and the models cannot improve. |
| 10 | Module G — industrial disaggregation | Independent of the utility path. Built as soon as the first paying industrial site is secured, because it funds everything else. |
| 11 | Modules C and D — asset health and forecasting | Require accumulated sensor history, so they cannot usefully precede a deployment. |
| 12 | Modules E, F, I, J | Post-pilot. Each is valuable and none is on the critical path to a recovered-kilowatt-hour figure. |


## 13.2  The critical path

The shortest route to a defensible recovered-kilowatt-hour figure runs through items 1, 2, 4, 5, 6, 7 and 9. Everything else, including the entire presentation layer beyond a functional interface, is off the critical path and should be deferred whenever the critical path is at risk.

The most likely failure mode of this project is building the dashboard first. It is the most visible component, the most satisfying to build, and the one AI-assisted tooling produces fastest. It is also worthless without the analytical layer beneath it, and time spent on it early is time not spent on the reconstruction problem, which is the genuinely hard part and the part on which the platform’s claim to novelty rests.

## 13.3  Buy, borrow, build

| Decision | Choice | Reasoning |
| --- | --- | --- |
| Power-flow computation | Borrow — pandapower, OpenDSS | Mature, validated, well documented. Building this is months of work to reach a worse result. |
| Time-series storage | Buy or borrow — established open-source time-series database | Commodity. No differentiation available. |
| Model training infrastructure | Borrow — standard Python analytical stack with experiment tracking | Commodity. |
| Sensing hardware | Build | Commercial units are one to two orders of magnitude too expensive, and the cost structure is the entire basis of feeder-level instrumentation. |
| Consumption reconstruction | Build | No existing product solves this because no other market needs it. This is the core intellectual property. |
| Loss attribution and solar discrimination | Build | Same reasoning. Published work assumes interval data and does not address simultaneous solar adoption. |
| Field operations application | Build | Generic field-service products exist but none captures structured outcomes in a form usable as training labels, which is the entire point. |
| Mapping and geospatial rendering | Borrow — open-source mapping libraries and OpenStreetMap | Commodity. |


# 14.  Resourcing, Cost and Timeline

All figures in this section are planning estimates prepared for internal budgeting. They are not quotations and must be confirmed against current supplier and service pricing before any commitment is made.

## 14.1  Skills required

| Skill | Where it is needed | Source |
| --- | --- | --- |
| Data engineering and backend development | Hierarchy, ingestion, storage, services | Founder, AI-assisted |
| Applied machine learning | Modules A to D | Founder, AI-assisted; external review recommended before any accuracy claim is made externally |
| Power systems engineering | Digital twin parameterisation, technical loss validation, device measurement standards | Bought in or partnered. This is the one area where a mistake is not recoverable by iteration, because an incorrect technical-loss model invalidates every attribution result. |
| Embedded firmware and electronics | Sensing device | Bought in for schematic review, calibration method and enclosure; firmware AI-assisted |
| Frontend development | Drill-down interface, field application | Founder, AI-assisted |
| Field survey | Feeder walk, conductor and transformer data capture | Contracted for the pilot period |


The power-systems engineering gap is the significant one. A chemical-engineering background supplies the analytical and process discipline but not distribution network practice, and the digital twin is the component where an undetected error propagates silently into every downstream result. An engagement with a qualified electrical engineer — an academic partnership with a university engineering department is the most economical route — should be secured before the twin is parameterised, not after.

## 14.2  Indicative pre-pilot cost

| Item | Basis | Indicative cost |
| --- | --- | --- |
| Sensing device prototypes (5 units) | Bill of materials per Section 6.2, plus iteration and spoilage | USD 700 – 1,400 |
| Test rig and reference instrumentation | Calibrated reference meter, variable load bank or equivalent, bench supplies | USD 400 – 1,200 |
| Electronics and power-systems specialist input | Schematic review, calibration methodology, twin parameterisation review | Negotiated; budget provision required |
| Cloud infrastructure, development period | Compute and storage at development scale | USD 30 – 120 per month |
| Cellular data for devices | Low-volume machine-to-machine SIMs | Per-SIM monthly; confirm with operator |
| AI-assisted development tooling | Existing subscription | Already incurred |
| Public datasets and libraries | All sources in Appendix C are free | Nil |


The pre-pilot cost is dominated by hardware iteration and specialist review, and is of an order that can be self-funded. The feeder pilot is a materially larger commitment — instrumentation across the feeder’s transformers, field survey, and installation — and Section 18 proposes that it be funded from Path A revenue rather than from capital.

## 14.3  Indicative timeline

| Period | Phase | Outcome |
| --- | --- | --- |
| Months 1–2 | Foundation | Hierarchy data model; synthetic generator; ingestion and storage; first device prototype on the bench. |
| Months 2–4 | Core analytics | Digital twin on the synthetic feeder; consumption reconstruction validated against held-out real interval data; device calibrated against reference. |
| Months 4–6 | Attribution and interface | Loss attribution operating on synthetic data with known ground truth; drill-down interface complete; the twenty-minute demonstration of Section 12.4 achievable. |
| Months 4–8 | Commercial entry | First industrial sites commissioned under Path A; disaggregation module built against real plant data; recurring revenue established. |
| Months 6–10 | Utility engagement | Pilot proposal to ZETDC with the demonstration in hand; verification methodology agreed in writing; feeder selected and surveyed. |
| Months 9–15 | Feeder pilot | Instrumentation installed; vending data ingested; full detection and inspection loop operating; recovered kilowatt-hours reported. |


Periods overlap deliberately. The commercial entry path runs in parallel with core analytics development and is not gated on it, because its purpose is to fund the programme and to establish operating experience with the hardware under real conditions.

# 15.  Validation and Acceptance Criteria

Each component has a defined condition under which it is considered to work. Without these, development proceeds indefinitely and no component is ever finished.

| Component | Acceptance condition |
| --- | --- |
| Synthetic generator | Generated load shapes are statistically indistinguishable from public reference data on diurnal profile, weekly pattern and load factor. Injected anomalies are recoverable by manual inspection of the ground truth. |
| Network hierarchy | A connection can be resolved to its transformer, feeder and substation, and any level can be aggregated from the level below, with no orphaned records. |
| Digital twin | Computed technical loss on the synthetic feeder matches the loss imposed by the generator within a stated tolerance across a range of loading conditions. |
| Module A — reconstruction | Mean absolute error at daily and monthly resolution against held-out real interval data, stated as a number with its uncertainty calibration. The transformer-level aggregate is the operative figure. |
| Sensing device | Energy measurement within a stated tolerance of a calibrated reference across the load range, under balanced and imbalanced conditions, with harmonic content present. |
| Module B — attribution | On synthetic data with known labels: precision at the top of the ranked queue, reported by cause class, with solar and bypass reported separately because conflating them is the failure that matters. |
| Field application | Complete offline case handling with synchronisation on reconnection, structured outcomes captured with no free-text-only path, and negative outcomes recorded. |
| Pilot | A recovered-kilowatt-hour figure computed under the verification methodology agreed in advance with the utility. |


One rule governs all external communication of these figures: a result obtained on synthetic data is reported as a result obtained on synthetic data. The temptation to present a synthetic precision figure as though it were a field result is the fastest available route to losing technical credibility permanently, and it will be detected, because the first question any competent evaluator asks is what the model was validated on.

# 16.  Legal, Regulatory and Data Protection

## 16.1  Consumption data is personal data

A record of when a household bought electricity, how much, and how quickly it was consumed reveals occupancy, routine, income pattern and absence. Under Zimbabwe’s Cyber and Data Protection Act [Chapter 12:07] this is personal data, and processing it carries obligations that must be addressed before any data is received rather than after.

- The lawful basis for processing must be established and documented, and the relationship between HJM Technologies and the utility — controller, joint controller or processor — must be settled in writing in the pilot agreement.

- A written data processing agreement must be in place before any extract is transferred, specifying purpose limitation, retention period, security measures, sub-processing, and deletion or return at termination.

- Data minimisation applies to the extract requested. A single feeder and a fixed historical window is both a smaller ask commercially and the correct position legally; requesting national data would be neither.

- Registration obligations for data controllers under the Act and its statutory instruments must be confirmed and complied with, and the position of a processor acting on a utility’s behalf clarified.

- Access within the platform is role-based, minimised, logged and auditable, and the audit log is itself part of the evidentiary standard in Section 10.3.

These obligations should be treated as a commercial advantage rather than a burden. A utility’s legal function is a real obstacle to any data-sharing arrangement, and arriving with a drafted processing agreement and a documented compliance position removes the most common reason such arrangements stall.

## 16.2  Operational technology boundary

The platform is read-only with respect to operational technology. It does not issue control commands, does not interface with protection or switching, and does not require connectivity to control systems. This removes an entire category of security risk and materially simplifies the utility’s internal approval. This boundary is architectural and must not be relaxed for convenience in later phases.

## 16.3  Enforcement and human decision

Model outputs are advisory. No disconnection, back-billing or enforcement action occurs without human review, physical confirmation and a recorded decision attributable to a named person. This is both an ethical requirement and a practical one: an automated accusation that proves wrong is a legal exposure and a reputational event that the platform would not survive.

## 16.4  Device and installation compliance

As noted in Section 6.5, equipment installed on utility assets is subject to the utility’s standards and installation on energised plant is restricted to qualified personnel. In addition, a cellular-connected device requires appropriate type approval for the communications module. Both must be confirmed before production quantities are ordered.

# 17.  Implementation Roadmap

The roadmap is deliberately narrow at the outset. A proposal that promises six capabilities simultaneously reads as unfocused to a technical evaluator; a proposal that demonstrates one capability to a measurable standard earns the right to build the rest.

| Phase | Duration | Activity | Success gate |
| --- | --- | --- | --- |
| Phase 0 Foundation | Months 1–6 | Build the data model and hierarchy. Build the synthetic generator. Develop consumption reconstruction against public and synthetic prepaid-style data. Build and bench-validate the first sensing devices. Construct the drill-down interface. | The twenty-minute demonstration of Section 12.4, with a stated reconstruction error measured against real held-out interval data. |
| Phase 1 Commercial entry | Months 4–8 | Deploy industrial energy intelligence at two to three paying sites. Commission monitoring, run load disaggregation, deliver quantified savings. | Named reference customers and recurring revenue funding subsequent phases. |
| Phase 2 Feeder pilot | Months 9–15 | One 11 kV feeder. Survey the network and build the digital twin. Install transformer monitors. Ingest vending data. Operate the full detection and inspection loop. | Verified recovered kilowatt-hours and demonstrated precision at the top of the case queue. |
| Phase 3 Proof and scale | Months 15–24 | Extend to a full substation. Introduce asset health, shedding intelligence and solar mapping. Establish automated regulatory reporting. | Independently verified recovery figure and a signed extension agreement. |
| Phase 4 Regional | Year 3 onward | Multi-utility configuration, additional territories, and publication of the sparse-instrumentation inference work. | Second utility engaged outside Zimbabwe. |


## 17.1  The pilot proposition

| One 11 kV feeder. Ninety days of measurement. One number reported — recovered kilowatt-hours. At no capital cost to the utility. |
| --- |


A pilot of this scope can be approved at operating level, does not require a procurement process, does not touch operational control systems, and carries no financial exposure. Every element of that framing is chosen to remove a reason to decline.

## 17.2  Feeder selection criteria

- A documented history of unexplained loss, so that there is something to find.

- A manageable number of distribution transformers, so that instrumentation cost is contained.

- A mixed customer base, so that results generalise beyond a single settlement type.

- Reasonable physical accessibility and acceptable security conditions for installation and inspection.

- An identified sponsor within the utility’s district management with the authority to authorise access and dispatch inspectors.

# 18.  Commercial Model

## 18.1  Utility engagement — performance-based compensation

A capital-constrained state utility will not readily approve a substantial software licence, and any process that requires formal procurement will consume a year or more before any technical work begins. The proposal therefore inverts the commercial structure entirely: HJM Technologies funds the pilot, including hardware, and is compensated as an agreed percentage of independently verified recovered revenue over a term of twenty-four to thirty-six months.

The effects of this structure are worth stating explicitly, because they are the substance of the pitch:

- No capital expenditure line, and therefore a materially lower approval threshold within the utility.

- Delivery risk transferred to the vendor, which is a straightforward position for a utility official to defend internally.

- Vendor incentives aligned with recovery rather than with software delivery.

- A verification methodology agreed in advance, which converts the eventual commercial discussion from a negotiation into an arithmetic exercise.

The verification methodology must be settled before the pilot begins. What constitutes recovered revenue, how it is measured, over what period it is attributed, and who validates the figure are all matters to be agreed in writing at the outset. Failure to do so is the most predictable way for a successful pilot to produce no commercial outcome.

## 18.2  Industrial customers — subscription

Monitoring hardware supplied and installed, with a monthly subscription per site covering the platform, analytics and reporting. Pricing is set by reference to demonstrated savings rather than to cost, and the proposition is straightforward for a plant manager to evaluate: the subscription is justified if identified savings exceed it, and the first month’s analysis establishes whether they do.

This path matters strategically as much as financially. It generates revenue within the first two quarters, it produces operating experience with the hardware and the disaggregation models under real conditions, and it means that the eventual approach to the utility is made by an operating company with named industrial customers rather than by a proposal.

It also funds the feeder pilot. The gain-share structure of Section 18.1 requires the vendor to carry the instrumentation cost, and Path A revenue is the intended source. The commercial sequencing is therefore not incidental to the technical plan; it is what makes the technical plan financeable without external capital.

## 18.3  Regulator and public sector

Automated reliability and loss reporting, and the distributed generation capacity map, are of direct value to the regulator and to policy formulation, and represent a licensing opportunity distinct from the utility relationship.

## 18.4  Regional expansion

The combination of high non-technical loss, prepaid metering, constrained generation and rapid unregistered solar adoption is common across the region. A platform proven in Zimbabwe addresses a market of comparable utilities without material re-engineering, provided portability is designed in from the beginning as specified in Section 11.6.

# 19.  Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Data access is not granted, or is granted too slowly. | Section 12 governs. The entire system is developed and demonstrated on synthetic and public data, so capability is proven before access is requested. The initial request is scoped to a single feeder and a fixed historical window. The industrial path proceeds regardless and does not depend on the utility at all. |
| False accusation of a lawful customer. | Solar and meter-failure discrimination is treated as a first-class modelling problem rather than an afterthought. Early operation optimises precision rather than recall. No enforcement action follows from a model output without human review and physical confirmation. |
| Institutional resistance where losses involve internal participation. | Executive-level sponsorship is secured before deployment. Early phases are framed and reported as asset protection and outage reduction. Internal integrity analytics are introduced only once the platform has established value on uncontroversial grounds. |
| Installed monitoring hardware is stolen or damaged. | Devices are of low unit value and have limited resale utility. Enclosures are tamper-evident and alarmed. Units are mounted within existing secured transformer enclosures where possible, and replacement cost is carried in the pilot budget as an expected line item. |
| Insufficient labelled data to reach useful model precision. | Staged training from unsupervised through weak supervision to full supervision, with physics-based features removing a large part of the variance. The field loop is designed to generate labels from the first week of operation, including from negative findings. |
| Pilot succeeds technically but produces no contract. | Verification methodology and commercial terms are agreed in writing before the pilot begins. Reporting is structured throughout around a single financial figure rather than technical metrics. |
| Currency instability undermines the value of gain-share compensation. | Recovery is measured and reported primarily in kilowatt-hours, with monetary conversion applied at an agreed reference basis. Multi-currency handling is built into the data model from the first version. |
| Connectivity and power interruptions degrade data collection. | Devices buffer locally and back-fill on reconnection, and report loss of supply before shutting down. All analytical modules are specified to operate on incomplete data with explicitly quantified uncertainty. |
| Synthetic data does not transfer to real conditions. | Synthetic distributions are calibrated against public real-world datasets wherever a public analogue exists, and the generator is treated as a component to be validated rather than assumed. Transfer failure is expected in some degree and the first weeks of real data are budgeted as a re-fitting period, not as a confirmation exercise. |
| Power-systems modelling error invalidates attribution. | External review of the digital twin parameterisation by a qualified electrical engineer before any attribution result is relied upon, per Section 14.1. The twin is validated against the synthetic generator's imposed losses before it is trusted on a real feeder. |
| Single-person key dependency. | All work is documented as specification rather than held as knowledge; infrastructure is reproducible from code; the research track is pursued through an academic partnership that creates a second locus of competence. |


# 20.  Value Proposition

## 20.1  For ZETDC

- Recovery of revenue currently lost to theft, bypass and undetected meter failure, measured and verifiable.

- Reduction in unplanned outages through transformer replacement scheduled ahead of failure rather than after it.

- Rapid detection of vandalism, materially shortening the associated outages and improving the prospect of interception.

- Correct separation of technical from non-technical loss, so that inspection effort and network reinforcement are each directed where they will work.

- A corrected and continuously maintained map of which connection sits beneath which transformer.

- A quantified forecast of revenue erosion from distributed solar, to inform tariff and investment strategy.

- Regulatory reporting generated from source data rather than assembled manually.

## 20.2  For the regulator and for policy

- Reliability and loss figures traceable to measurement rather than to estimation.

- A national map of installed distributed generation capacity that does not presently exist.

- An evidentiary basis for tariff, net-metering and network investment policy.

## 20.3  For industrial and commercial customers

- Consumption and cost attributed to individual processes and machines.

- Quantified reduction in maximum demand charges and power-factor penalties.

- Early identification of developing equipment faults from electrical signatures.

- Rational dispatch decisions between grid supply, on-site generation and storage.

## 20.4  For consumers

- More dependable and accurately published load-shedding schedules.

- Shorter outages, as failing assets are replaced before failure and vandalism is detected promptly.

- More equitable distribution of shedding hours across communities over time.

- Reduced pressure on tariffs to the extent that losses are recovered from those causing them.

# 21.  Immediate Next Steps

The following are ordered and specific. Each has a defined output, and none depends on an external party except where stated.

| # | Action | Output |
| --- | --- | --- |
| 1 | Build the network hierarchy data model. | A schema in which a connection resolves to transformer, feeder, substation and region, with aggregation working in both directions. |
| 2 | Build the synthetic vending and network generator. | A configurable synthetic feeder with known true consumption, known technical loss and injected labelled anomalies. |
| 3 | Acquire the public datasets in Appendix C and convert interval data into synthetic purchase sequences. | A held-out evaluation set with true interval consumption known, for measuring reconstruction error. |
| 4 | Develop Module A against that evaluation set. | A stated mean absolute error at daily and monthly resolution, with uncertainty calibration. |
| 5 | Design, assemble and bench-test the first sensing device; confirm the bill of materials against current supplier quotations. | A calibrated device with a measured accuracy figure against a reference instrument. |
| 6 | Build the digital twin on the synthetic feeder and validate computed technical loss against the generator's imposed loss. | A twin whose loss computation is verified, and a documented tolerance. |
| 7 | Build Module B on synthetic data with known labels. | Precision at the top of the ranked queue, reported by cause class, with solar and bypass separated. |
| 8 | Build the drill-down interface over the synthetic feeder, including the injected theft and solar scenarios. | The twenty-minute demonstration specified in Section 12.4. |
| 9 | Secure power-systems engineering review, ideally through a university engineering department. | Independent validation of the twin parameterisation and the device measurement method. |
| 10 | Identify and approach two to three industrial prospects for the Path A commercial entry. | A first paying site, and real plant data for the disaggregation module. |
| 11 | Draft the data processing agreement and compliance position in advance of any approach. | A pack that removes the utility's most common reason to delay. |
| 12 | Prepare the ZETDC pilot proposal — one feeder, ninety days, one number, no capital cost — with the verification methodology specified in advance. | A proposal supported by a working demonstration rather than a description. |
| 13 | Identify a sponsor within ZETDC district management and, separately, a route to the regulator. | A named internal sponsor with authority to authorise access and dispatch inspectors. |


# Appendix A — Summary of Analytical Modules

| Module | Approach | Principal inputs | Output | Cold start |
| --- | --- | --- | --- | --- |
| A. Consumption estimation | Latent state-space or sequence model | Vending events, tariff band, shedding schedule, weather | Estimated consumption profile with uncertainty | Calibrate against interval-metered commercial customers |
| B. Loss attribution | Autoencoder and isolation forest, then gradient-boosted classification | Transformer energy, reconstructed consumption, modelled technical loss, irradiance, peer group | Ranked case queue with predicted cause and confidence | Unsupervised, then weak supervision, then field labels |
| C. Asset health | Survival analysis with censored data | Loading, thermal behaviour, harmonics, imbalance, fault history, age | Hazard function, remaining useful life, risk ranking | Historical failures plus physics-based thermal ageing prior |
| D. Demand forecasting | Gradient-boosted quantile regression | Lagged demand, calendar, temperature, shedding history | Day- and week-ahead forecasts with uncertainty bands | Historical system demand records |
| E. Shedding allocation | Mixed-integer optimisation (not machine learning) | Forecast demand, available generation, criticality, equity history, asset stress | Feeder-level shedding schedule with justification | Not applicable |
| F. Solar intelligence | Behavioural inference plus image segmentation | Consumption shape, irradiance, aerial imagery | Installed capacity map and revenue erosion forecast | Published segmentation models transfer well |
| G. Industrial NILM | Sequence-to-point convolutional network | High-resolution plant aggregate demand | Per-machine energy and cost attribution | Short supervised switching exercise at commissioning |
| H. Network inference | Graph neural network over topology | Sparse node measurements, network graph | State estimates at uninstrumented nodes; topological anomaly detection | Digital twin simulation generates initial training data |
| I. Inspection vision | Optical character recognition and object detection | Field photographs with location metadata | Meter readings, tamper indicators, visit verification | Pre-trained models with modest local fine-tuning |
| J. Operator language interface | Retrieval-constrained language model | Platform data and model outputs only | Natural-language query, explanations, drafted reports, translation | Available immediately; constrained to retrieved data |


# Appendix B — Pilot Success Metrics

| Metric | Definition | Indicative target |
| --- | --- | --- |
| Recovered energy | Kilowatt-hours brought back into billing as a direct result of platform-generated cases, measured over the ninety days following intervention | Primary headline figure |
| Queue precision | Proportion of dispatched inspections in which the predicted cause was confirmed on site | Improving cycle on cycle |
| Recovery per inspection | Recovered energy divided by inspections dispatched | Rising trend |
| Loss decomposition | Proportion of feeder loss attributable to modelled technical causes versus residual | Established and defensible |
| Association accuracy | Proportion of connections whose transformer association was verified or corrected | Above ninety per cent on the pilot feeder |
| Asset risk ranking | Concordance between predicted asset risk ordering and observed events | Established baseline for extension |
| Device availability | Proportion of expected sensor readings successfully received | Above ninety-five per cent excluding shedding windows |
| Vandalism response | Elapsed time from asset disturbance to alert raised | Under fifteen minutes |


# Appendix C — Development Resources

All resources listed are publicly available at no cost at the date of this version. Licence terms vary and must be checked before any commercial use; several carry restrictions on redistribution or require attribution. Availability and access conditions should be re-confirmed before the development plan depends on any individual source.

## C.1  Open-source libraries

| Library | Role |
| --- | --- |
| pandapower | Network modelling and balanced power flow for the feeder digital twin. |
| OpenDSS, via its Python interface | Unbalanced three-phase analysis of the low-voltage network, where phase imbalance materially affects computed loss. |
| Standard Python analytical stack | Model development, gradient boosting, sequence models and experiment tracking. |
| Survival analysis libraries for Python | Time-to-event modelling for transformer remaining useful life. |
| Time-series database (open-source) | Storage of device telemetry and reconstructed consumption at interval resolution. |
| MQTT broker (open-source) | Device telemetry ingestion. |
| Open-source mapping libraries with OpenStreetMap | Geographic rendering of the network hierarchy and case locations. |


## C.2  Public datasets

| Dataset category | Use in this programme |
| --- | --- |
| Smart-meter trial datasets with half-hourly household consumption | Source of realistic load shapes to drive the synthetic generator, and the ground truth against which consumption reconstruction is evaluated after conversion into synthetic prepaid purchase sequences. |
| Labelled electricity-theft detection datasets | Architecture development and benchmarking for the loss-attribution classifier before any Zimbabwean labels exist. |
| Solar-home datasets carrying gross generation and consumption separately | Development of the solar-versus-theft discrimination, since these datasets contain exactly the decomposition the module must infer. |
| Open satellite irradiance and meteorological reanalysis products | Irradiance and temperature features. These are also the intended production source, so developing against them avoids a later substitution. |
| Non-intrusive load monitoring datasets | Architecture development for industrial load disaggregation, with site-specific commissioning data collected at the first real customer. |
| Transformer loading and thermal ageing guidance (published standards) | The physics-based prior constraining the asset-health model before observed failures accumulate. |


Prepared by HJM Technologies  |  National Grid Intelligence Platform, Version 3.0  |  September 2026

Internal development specification. Cost figures are planning estimates, not quotations. No engagement with ZETDC has been concluded at the date of this version.
