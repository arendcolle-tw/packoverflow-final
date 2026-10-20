# Knowly stage script

Every prompt below goes into `#ask_knowly` in Slack. Knowly answers in the thread.

## Before going on stage

```bash
python demo/seed/seed.py --url http://127.0.0.1:8091 --admin-token=$KNOWLY_ADMIN_TOKEN --sessions
```

The script creates the members tristan, alberic, sanne and joris (plus the background colleagues when `demo/seed/background.json` exists), loads their facts and runs three Claude Code sessions that the recorder turns into facts. It is safe to run again.

The team in the data: Tristan and Alberic are payroll consultants with client portfolios; Sanne and Joris are colleagues. Clients: Brouwerij Vandaele, Bakkerij Peeters, Logistiek De Smet, Zorggroep Linde, Apotheek Wouters and the new client Garage Claes.

## A. Answered from facts

| # | Ask as | Prompt | Expected answer | Relies on |
|---|---|---|---|---|
| A1 | alberic | What's the payroll cutoff for Brouwerij Vandaele? | The 18th, decided by Tristan because the brewery's timesheets only close on the 17th. | Tristan, "Brouwerij Vandaele payroll cutoff" |
| A2 | tristan | Which of our clients use mysdworx self-service? | Zorggroep Linde (full self-service, nurses work nights), Logistiek De Smet (drivers, payslips only), Apotheek Wouters (from the first payslip); Bakkerij Peeters stays on paper until January. | Alberic, Tristan and Sanne, four mysdworx facts |
| A3 | alberic | How do we handle Legal Watch alerts? | Tristan triages them on Monday and forwards only those that hit a joint committee in the portfolio; PC 330 alerts go to Joris; every alert that affects a client gets a note in the client file within a week. | Tristan "Legal Watch alerts: Monday triage", Joris's two Legal Watch facts |
| A4 | alberic | What do we check before the January indexation goes live? | 20 payslips per joint committee compared with December, then two sign-offs (Tristan and Alberic) before release, because one PC 200 client got the indexation twice last year. | Tristan "January indexation check before go-live" and "sign-off", Alberic "who checks which clients" |

## B. Answered from a Claude Code session

| # | Ask as | Prompt | Expected answer | Relies on |
|---|---|---|---|---|
| B1 | alberic | Why do we only retry the KBC payroll export three times? | Tristan set 3 retries instead of 5 because the bank closes the SFTP window at 18:00 and a late file is rejected anyway. | Tristan's session "nightly bank export" |
| B2 | tristan | Which job classification do we use for the Bakkerij Peeters pay transparency report? | The sector classification their pay scales already follow, chosen by Alberic because the works council negotiates on those levels; the two office staff are grouped with shop staff so no salary can be read off. | Alberic's session "Bakkerij Peeters pay transparency" |

Spare: "How many parallel runs does Garage Claes get?" One, in December, because the previous provider's contract ends on 31 December (Alberic's session "Garage Claes onboarding").

## C. Nobody knows, Knowly pings Tristan

Ask as alberic. Knowly says nothing in Knowly answers it yet, shows Tristan's related export facts and tags Tristan.

| # | Prompt | Related facts Knowly shows | Tristan replies in the thread |
|---|---|---|---|
| C1 | What time does the nightly payroll export start? | 3 retries before the 18:00 window, who to call when the export fails | It starts at 16:00 so three retries still finish before the bank's 18:00 cutoff |
| C2 | How long do we keep the payroll export files on the SFTP server? | One SFTP file per client, SFTP key rotation for the KBC export | We keep them 30 days and then archive them, because clients sometimes ask for a resend in the month after payday |

## D. Nobody knows, Knowly pings Alberic

Ask as tristan. Knowly shows Alberic's related facts and tags Alberic.

| # | Prompt | Related facts Knowly shows | Alberic replies in the thread |
|---|---|---|---|
| D1 | Does Bakkerij Peeters get its eco-cheques on paper or electronically? | Bakkerij Peeters eco-cheques paid in July | Electronically, on the same card as their meal vouchers, because the bakers asked for one card instead of two |
| D2 | Who at Zorggroep Linde signs off the pay transparency report? | Linde's report grouped by the IFIC classification | Els Martens, their HR director, signs it off a week before it goes to the works council, because she wants to correct job titles first |

## Stage flow

1. Show that a session became a fact. As alberic, post B1. Knowly answers with Tristan's 3 retries and his reason. Say: "Tristan worked on the bank export with Claude and overruled it on the retries. Knowly kept only his decision and his reason."
2. As alberic, post C1: `What time does the nightly payroll export start?` Knowly says the start time is not recorded, shows Tristan's retry fact and tags Tristan.
3. As tristan, reply in that thread: `It starts at 16:00 so three retries still finish before the bank's 18:00 cutoff`. Knowly puts a check mark on the reply and stores it as Tristan's fact.
4. As alberic, post C1 again as a new message. Knowly answers: 16:00, decided by Tristan, so three retries finish before the bank's 18:00 cutoff.

## Combined answers

| # | Ask as | Prompt | Expected answer | Relies on |
|---|---|---|---|---|
| W1 | tristan | What gets paid in June at Brouwerij Vandaele? | The first half of the year-end premium (Tristan: summer is their busiest season) and the eco-cheques with it (Alberic: the client asked for one bigger June payslip). | Tristan "year-end premium split", Alberic "Brouwerij Vandaele eco-cheques" |
| W2 | tristan | We're onboarding Garage Claes for January. What should I plan for the parallel runs and the January indexation? | The standard is two parallel runs (Tristan), but Garage Claes gets one in December because their previous provider's contract ends on 31 December (Alberic); the January run still needs the 20-payslip indexation check and two sign-offs. | Alberic's session "Garage Claes onboarding", Tristan's onboarding and indexation facts |
