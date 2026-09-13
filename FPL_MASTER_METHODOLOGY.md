# FPL Master Methodology

Status: standing cross-chat decision methodology for personal FPL analysis. Use this framework by default unless the user explicitly overrides it.

## 1. Decision objective

Optimize the whole 15-player squad, not isolated player rankings.

Primary objective: maximize risk-adjusted expected FPL return over multiple horizons after accounting for transfer cost, captaincy, bench utility, club-slot constraints, affordability, tactical role, uncertainty and future flexibility.

A player may lose head-to-head but still be the better squad choice if the saving creates a larger package gain elsewhere. Conversely, a player with the highest raw projection is not automatically the best transfer if the hit, price, club slot or downstream structure destroys net value.

Default horizons follow the engine package optimizer: 3/5/10/15 GW with existing configured weights. Early-season evidence must be Bayesian-shrunk and uncertainty remains explicit.

## 2. Universal layer for every player

Evaluate all candidates on the following dimensions before position-specific scoring:

- Official FPL identity, position, price, club and availability authority.
- P(start), xMins and role-specific minutes confidence.
- Injury, suspension and availability risk.
- Historical prior and prior-season role.
- Current-season underlying performance with Bayesian early-season shrinkage.
- Tactical role and average position.
- Role stability, not only starter status.
- Coach/system fit.
- Team attack/defence quality as relevant to the position.
- Opponent quality and opponent style, not FDR alone.
- Home/away context.
- European/cup/competitive-load congestion and likely rotation.
- Set-piece and penalty responsibilities where relevant.
- Historical sustainability versus short-sample overperformance.
- Price, points per million and price elasticity.
- Exact sell value / affordability when authenticated data is available.
- Transfer hit and hit-adjusted net benefit.
- Club-slot opportunity cost.
- Bench utility.
- Future transfer flexibility and cash-in-bank optionality.
- Correlation / team-cluster risk.
- Volatility, uncertainty, floor and ceiling.
- Ownership, EO and mini-league context only as a strategy overlay after football quality and package EV, never as primary football authority.

## 3. Four-layer model

### Layer 1: Availability & Minutes

- P(start)
- xMins
- injury/suspension
- rotation risk
- congestion
- substitution timing

### Layer 2: Football Quality & Role

- underlying production
- historical prior
- tactical position
- coach fit
- set-piece/penalty role
- focality / involvement
- role quality

Minutes are not equal. Use the concept:

`Effective Role Minutes = xMins × Role Quality`

Example: 80 minutes as a central No.9 can be materially more valuable than 80 minutes as a deeper No.10 for an FPL forward.

### Layer 3: Environment

- team attack/defence strength
- opponent strength
- opponent tactical style
- fixture sequence
- home/away
- expected game state
- competition schedule and recovery time

### Layer 4: FPL Economics & Strategy

- price
- value / £
- transfer cost
- club slot
- captaincy
- bench utility
- structure and formation flexibility
- cash-in-bank
- future moves
- EO / mini-league overlay

## 4. Goalkeeper-specific methodology

Evaluate:

- team xGC
- clean-sheet probability
- shots on target faced
- save volume
- PSxG / shot-stopping quality
- goals prevented versus expected
- big-chance saves
- BPS/bonus profile
- penalty-save probability
- opponent shot profile
- expected shot location and shot quality
- fixture pairing with second goalkeeper
- correlation / double-up with owned defenders
- club-slot opportunity cost
- price and hit-adjusted upgrade value

Do not assess a goalkeeper only from clean-sheet odds. A strong goalkeeper fixture can be a combination of reasonable clean-sheet probability plus high low-quality shot volume, creating save and bonus upside.

For two cheap keepers, assess the pair as a package:

`Pairing EV = expected points from optimal weekly keeper selection - selection-error risk - opportunity cost`

A premium goalkeeper must beat the cheap-pair package after hit and capital cost, not merely beat one cheap goalkeeper head-to-head.

## 5. Defender-specific methodology

Evaluate:

- team xGC and clean-sheet probability
- defensive contributions per 90
- probability of reaching the defensive-contribution scoring threshold
- attacking xG, xA and xGI
- shots, shots in box and box touches
- key passes, crosses and chance creation
- set-piece role
- aerial threat
- CB / FB / WB / inverted role
- average position and attacking height
- clean-sheet dependency
- BPS profile
- cards, fouls and disciplinary risk
- opponent attack channel
- opponent cross frequency
- opponent set-piece weakness
- opponent aerial profile
- high-line / low-block matchup
- expected possession and defensive workload
- substitution-before-60 risk

Use a derived `Points Route Diversification Score`.

A defender with several credible routes such as clean sheet + defensive contributions + attacking return + bonus is more robust than a defender whose EV depends almost entirely on one route.

Matchup style can invert generic FDR. A difficult opponent may increase defensive-contribution opportunities for a CB; a low block may improve chance-creation potential for an attacking full-back.

## 6. Midfielder-specific methodology

Evaluate:

- npxG
- xA
- xGI
- shots
- shots in box
- shot location / shot quality
- big chances
- box touches
- key passes and chances created
- share of team xG/xA
- share of team shots / big chances where useful
- penalty duty
- direct free kicks and corners
- winger / inside-forward / No.10 / advanced 8 / deep 8 / second-striker role
- average position
- penalty-box occupancy
- defensive-contribution probability
- clean-sheet point route
- BPS profile
- opponent full-back / half-space matchup
- suitability versus high line versus low block
- captaincy utility where relevant

Role proximity to goal is mandatory. The same player can change materially as an FPL asset if moved from a free No.10 to a double pivot, or from a touchline winger to an inside forward.

Use team involvement share to distinguish a player who dominates a weaker attack from one who owns a smaller share of a stronger attack.

## 7. Forward-specific methodology

Evaluate:

- npxG
- xGI
- big-chance share
- shots in box
- shot quality / xG per shot
- box touches
- penalty duty
- share of team xG
- share of team shots and big chances
- centrality / focal-point role
- No.9 versus false-9 versus No.10 versus wing role
- historical finishing above/below xG
- service quality
- opponent centre-back matchup
- opponent high-line vulnerability
- aerial mismatch
- BPS profile
- blank/haul distribution
- captaincy ceiling

Add a `Finishing Prior` combining historical conversion, shot location, body-part mix and big-chance mix. Do not regress proven elite finishers completely to league-average conversion after small samples.

Add a `Focality Score` using the player's share of team xG, shots, big chances, box touches and penalty-area receptions.

Role stability is mandatory. A forward who remains a starter but is moved from No.9 to a deeper No.10 must receive a meaningful downgrade even when xMins stays unchanged.

## 8. Package and structure principles

Always compare packages, not only players.

Examples:

- premium MID + weak FWD/DEF versus cheaper premium MID + upgraded FWD/DEF
- premium GK versus two-value-GK rotation package
- premium DEF versus two mid-price defenders plus downstream upgrade
- premium FWD versus value FWD plus stronger MID/DEF

Use hit-adjusted net value:

`Net Package Gain = projected package gain - transfer hits - structural opportunity cost`

A transfer does not need to repay a hit in one GW, but it should have a credible positive net benefit over the relevant 3-5 GW horizon unless it is strategic infrastructure for a longer plan.

Do not spend hits merely to make the squad look cleaner. Low-impact bench and goalkeeper changes usually have the highest burden of proof.

## 9. Captaincy and formation

Captaincy is a squad-level asset. A premium player with low likelihood of receiving the armband has lower structural utility than the same raw projection may imply.

Formation is dynamic. Default to the formation with the highest package EV for the current fixture set, not a permanently fixed 3-4-3, 3-5-2 or 4-4-2.

Assess whether money placed in the fifth midfielder, fourth defender or third forward will actually be used often enough to justify the capital.

## 10. Required outputs for player/package comparison

For serious comparisons, report at minimum:

- expected points by relevant horizon
- floor / P10
- median
- ceiling / P90
- P(start)
- xMins
- role confidence
- coach/system fit
- fixture fit
- underlying sustainability / Bayesian confidence
- value per £
- route-to-points profile
- replacement / opportunity cost
- club-slot effect
- hit-adjusted package EV
- future flexibility / ITB effect
- key evidence that could change the conclusion

When Monte Carlo or exact optimizer output is unavailable, do not invent numerical probabilities. State clearly when the conclusion is structural / evidence-based rather than generated by a live simulation.

## 11. Evidence and governance rules

- Official FPL is authoritative for official identity, price, position, ownership, scoring and official availability fields.
- Fresh V6 data may enrich analysis but V6 itself has no prediction or recommendation authority.
- Tactical claims require evidence and must not be invented from nominal FPL position.
- One-match haul is a trigger for review, not an automatic buy signal.
- Price movement changes timing, not football authority.
- Watchlists are not the player universe.
- Full relevant Official FPL universe should be screened before pruning.
- Early-season small samples receive adaptive Bayesian shrinkage and wider uncertainty.
- Current-team decisions distinguish `fresh-build optimum` from `transition-adjusted optimum`.
- Existing ownership matters because avoiding a transfer/hit has value.
- Mini-league strategy is used only when current reliable mini-league evidence is available.

## 12. Standing cross-chat instruction

For future FPL chats, use this document as the default methodology and do not require the user to restate these dimensions. New methodological improvements agreed with the user should be appended or versioned here rather than replacing established rules silently.
