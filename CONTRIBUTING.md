# Contributing to Elastifund

## The Deal

Elastifund is open source. You can read it, fork it, run it, improve it. But if you're part of this community, here's the social contract:

1. **Contribute regularly.** Code, research, backtests, bug reports, documentation. Show up.
2. **20% of net trading profits go to veterans.** If you run this system and make money, 20% of your net P&L goes to veteran suicide prevention organizations. This is the mission. It's why we exist.
3. **Be transparent.** Log your trades. Share your results. We all learn from each other's data.

This isn't legally enforceable. It's a handshake agreement between people who want to build something that matters.

## How to Contribute

### 1. Find something to work on

- Check the [research_dispatch/](research_dispatch/) folder for prioritized research tasks
- Look at open issues on GitHub
- Run backtests and report results
- Find new edge strategies

### 2. Set up your dev environment

```bash
git clone git@github.com:CrunchyJohnHaven/elastifund.git
cd elastifund/polymarket-bot
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v  # All tests should pass
```

### 3. Make your changes

- Write tests for new functionality
- Run the full test suite before submitting
- Keep PRs focused — one feature or fix per PR

### 4. Submit a PR

- Clear description of what changed and why
- Include backtest results if the change affects trading logic
- Tag with relevant labels (edge, risk, infra, research)

## Code Style

- Python 3.10+
- Type hints on public functions
- Tests in `tests/` mirroring `src/` structure
- No secrets in code (use .env)

## Research Contributions

Not a coder? You can still contribute:

- **Market analysis** — Find categories or market types where the system underperforms
- **Prompt engineering** — Improve Claude's probability estimation prompts
- **Data collection** — Historical market data, resolution patterns, fee analysis
- **Strategy ideas** — New edges, new signals, new approaches

Write up findings in markdown and submit as a PR to `research/`.

## Veterans Commitment

Organizations we support (contributors choose where their 20% goes):

- [Veterans Crisis Line](https://www.veteranscrisisline.net/)
- [Stop Soldier Suicide](https://stopsoldiersuicide.org/)
- [22Until None](https://www.22untilnone.org/)
- Or any verified veteran suicide prevention nonprofit

Track your contributions however works for you. Monthly self-reporting is fine. We trust each other.

## Questions?

Open an issue or reach out to John Bradley (johnhavenbradley@gmail.com).
