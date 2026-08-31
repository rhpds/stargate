Feature: Durable functional alignment pipeline
  Scenario: Repeated AAP collection is idempotent
    Given the same failed job event is collected twice
    When both collections are persisted
    Then one source event and one evaluation exist

  Scenario: A diagnosis claims evidence exclusively
    Given one unresolved source event and two investigation workers
    When both workers attempt to claim the event
    Then exactly one investigation owns the evidence

  Scenario: Slack is delivered once after actionable diagnosis
    Given a completed actionable diagnosis
    When delivery processing runs repeatedly or restarts
    Then one notification ledger record is sent

  Scenario: Jira requires operator approval
    Given a reviewed actionable diagnosis
    When a Jira draft is generated
    Then no Jira request occurs until its pending action is approved

  Scenario: Knowledge requires review
    Given an unreviewed completed diagnosis
    When publication is requested
    Then publication is rejected

  Scenario: A catalog regression uses an observed baseline
    Given a catalog item with at least ninety percent prior success
    And its three most recent jobs failed
    When trend detection runs
    Then one catalog regression signal is persisted
