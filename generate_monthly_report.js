const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, LevelFormat,
  HeadingLevel, BorderStyle, WidthType, ShadingType,
  PageNumber, PageBreak, TabStopType, TabStopPosition
} = require("docx");

// ── Color palette ──
const NAVY = "1B3A5C";
const DARK_GRAY = "333333";
const MED_GRAY = "666666";
const LIGHT_GRAY = "F2F4F7";
const ACCENT_BLUE = "2E75B6";
const HEADER_BG = "1B3A5C";
const HEADER_TEXT = "FFFFFF";
const GREEN = "1D7324";
const RED = "B91C1C";
const YELLOW = "92640A";

// ── Helpers ──
const DXA_INCH = 1440;
const PAGE_W = 12240; // US Letter
const PAGE_H = 15840;
const MARGIN = DXA_INCH; // 1 inch
const CONTENT_W = PAGE_W - 2 * MARGIN; // 9360

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const noBorders = {
  top: { style: BorderStyle.NONE, size: 0 },
  bottom: { style: BorderStyle.NONE, size: 0 },
  left: { style: BorderStyle.NONE, size: 0 },
  right: { style: BorderStyle.NONE, size: 0 },
};
const cellPad = { top: 60, bottom: 60, left: 100, right: 100 };

function headerCell(text, width) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    shading: { fill: HEADER_BG, type: ShadingType.CLEAR },
    margins: cellPad,
    verticalAlign: "center",
    children: [new Paragraph({
      spacing: { before: 0, after: 0 },
      children: [new TextRun({ text, bold: true, font: "Arial", size: 18, color: HEADER_TEXT })]
    })]
  });
}

function dataCell(text, width, opts = {}) {
  const color = opts.color || DARK_GRAY;
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    shading: opts.bg ? { fill: opts.bg, type: ShadingType.CLEAR } : undefined,
    margins: cellPad,
    verticalAlign: "center",
    children: [new Paragraph({
      spacing: { before: 0, after: 0 },
      alignment: opts.align || AlignmentType.LEFT,
      children: [new TextRun({
        text,
        font: "Arial",
        size: opts.size || 18,
        bold: opts.bold || false,
        color,
      })]
    })]
  });
}

function sectionHeading(text) {
  return new Paragraph({
    spacing: { before: 300, after: 120 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: ACCENT_BLUE, space: 4 } },
    children: [new TextRun({ text: text.toUpperCase(), font: "Arial", size: 22, bold: true, color: NAVY })]
  });
}

function bodyText(text, opts = {}) {
  return new Paragraph({
    spacing: { before: opts.before || 60, after: opts.after || 60 },
    alignment: opts.align || AlignmentType.LEFT,
    children: [new TextRun({ text, font: "Arial", size: 19, color: opts.color || DARK_GRAY })]
  });
}

function label(text) {
  return new Paragraph({
    spacing: { before: 0, after: 0 },
    children: [new TextRun({ text, font: "Arial", size: 14, color: MED_GRAY, italics: true })]
  });
}

function paperTradingBanner() {
  return new Paragraph({
    spacing: { before: 120, after: 120 },
    alignment: AlignmentType.CENTER,
    shading: { fill: "FFF3CD", type: ShadingType.CLEAR },
    border: {
      top: { style: BorderStyle.SINGLE, size: 2, color: YELLOW },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: YELLOW },
      left: { style: BorderStyle.SINGLE, size: 2, color: YELLOW },
      right: { style: BorderStyle.SINGLE, size: 2, color: YELLOW },
    },
    children: [new TextRun({
      text: "PAPER TRADING — All data reflects simulated trades and backtested results. Not live capital.",
      font: "Arial", size: 17, bold: true, color: YELLOW,
    })]
  });
}

// ── Build Document ──
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 20 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: NAVY },
        paragraph: { spacing: { before: 0, after: 120 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial", color: NAVY },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
    ]
  },
  numbering: {
    config: [{
      reference: "bullets",
      levels: [{ level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } } }]
    }]
  },
  sections: [{
    properties: {
      page: {
        size: { width: PAGE_W, height: PAGE_H },
        margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN }
      }
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          spacing: { after: 0 },
          border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: ACCENT_BLUE, space: 4 } },
          children: [
            new TextRun({ text: "Predictive Alpha Fund", font: "Arial", size: 18, bold: true, color: NAVY }),
            new TextRun({ text: "\tMonthly Investor Report", font: "Arial", size: 16, color: MED_GRAY }),
          ],
          tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
        })]
      })
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          spacing: { before: 0 },
          border: { top: { style: BorderStyle.SINGLE, size: 2, color: "CCCCCC", space: 4 } },
          children: [
            new TextRun({ text: "CONFIDENTIAL", font: "Arial", size: 14, color: MED_GRAY, italics: true }),
            new TextRun({ text: "\tPage ", font: "Arial", size: 14, color: MED_GRAY }),
            new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 14, color: MED_GRAY }),
          ],
          tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
        })]
      })
    },
    children: [
      // ── TITLE BLOCK ──
      new Paragraph({
        spacing: { before: 0, after: 0 },
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "PREDICTIVE ALPHA FUND", font: "Arial", size: 40, bold: true, color: NAVY })]
      }),
      new Paragraph({
        spacing: { before: 80, after: 0 },
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "Monthly Performance Report", font: "Arial", size: 26, color: MED_GRAY })]
      }),
      new Paragraph({
        spacing: { before: 80, after: 0 },
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "March 2026", font: "Arial", size: 28, bold: true, color: NAVY })]
      }),
      new Paragraph({
        spacing: { before: 60, after: 120 },
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "Prepared: March 5, 2026", font: "Arial", size: 18, color: MED_GRAY })]
      }),

      paperTradingBanner(),

      // ── EXECUTIVE SUMMARY ──
      sectionHeading("Executive Summary"),
      bodyText(
        "Predictive Alpha Fund launched paper trading operations in March 2026, deploying an AI-powered automated trading system on Polymarket prediction markets. The system completed a comprehensive 532-market backtest demonstrating a 64.9% win rate and positive expected value across all strategy variants. Our best-performing strategy (Calibrated + Selective) achieved an 83.1% win rate on historical data. Paper trading is now live on our VPS infrastructure, scanning 100 markets per cycle with 18 signals generated per scan."
      ),

      // ── PERFORMANCE TABLE ──
      sectionHeading("Performance Summary"),
      label("All figures from paper trading and backtest. No live capital deployed."),

      new Table({
        width: { size: CONTENT_W, type: WidthType.DXA },
        columnWidths: [4680, 4680],
        rows: [
          new TableRow({ children: [headerCell("Metric", 4680), headerCell("Value", 4680)] }),
          new TableRow({ children: [dataCell("Starting NAV", 4680), dataCell("$75.00 (USDC)", 4680, { bold: true })] }),
          new TableRow({ children: [dataCell("Ending NAV (paper)", 4680), dataCell("$75.00 (no resolved trades yet)", 4680, { bold: true })] }),
          new TableRow({ children: [dataCell("Monthly Return %", 4680), dataCell("0.00% (awaiting resolution)", 4680)] }),
          new TableRow({ children: [dataCell("Benchmark (Polymarket avg)", 4680), dataCell("N/A (first month)", 4680)] }),
          new TableRow({ children: [dataCell("Cash Deployed", 4680), dataCell("$68.00 (34 positions \u00D7 $2)", 4680)] }),
          new TableRow({ children: [dataCell("Cash Remaining", 4680), dataCell("$7.00", 4680)] }),
          new TableRow({ children: [dataCell("Backtest Win Rate (532 mkts)", 4680), dataCell("64.9%", 4680, { bold: true, color: GREEN })] }),
          new TableRow({ children: [dataCell("Best Strategy Win Rate", 4680), dataCell("83.1% (Calibrated + Selective)", 4680, { bold: true, color: GREEN })] }),
        ]
      }),

      // ── TRADE ACTIVITY ──
      sectionHeading("Trade Activity"),
      label("Paper trading positions entered since system launch."),

      new Table({
        width: { size: CONTENT_W, type: WidthType.DXA },
        columnWidths: [4680, 4680],
        rows: [
          new TableRow({ children: [headerCell("Metric", 4680), headerCell("Value", 4680)] }),
          new TableRow({ children: [dataCell("Total Positions Entered", 4680), dataCell("34", 4680, { bold: true })] }),
          new TableRow({ children: [dataCell("Resolved (Wins)", 4680), dataCell("0 (awaiting resolution)", 4680)] }),
          new TableRow({ children: [dataCell("Resolved (Losses)", 4680), dataCell("0 (awaiting resolution)", 4680)] }),
          new TableRow({ children: [dataCell("Signals per Scan Cycle", 4680), dataCell("18 avg", 4680)] }),
          new TableRow({ children: [dataCell("Markets Scanned per Cycle", 4680), dataCell("100", 4680)] }),
          new TableRow({ children: [dataCell("Best Trade (backtest)", 4680), dataCell("+$2.00 (multiple, max payout)", 4680, { color: GREEN })] }),
          new TableRow({ children: [dataCell("Worst Trade (backtest)", 4680), dataCell("-$2.00 (multiple, max loss)", 4680, { color: RED })] }),
        ]
      }),

      // Page break
      new Paragraph({ children: [new PageBreak()] }),

      // ── STRATEGY BREAKDOWN ──
      sectionHeading("Strategy Breakdown by Category"),
      label("Backtest performance by market category (532 resolved markets)."),

      new Table({
        width: { size: CONTENT_W, type: WidthType.DXA },
        columnWidths: [2340, 1560, 1560, 1560, 2340],
        rows: [
          new TableRow({ children: [
            headerCell("Category", 2340), headerCell("Priority", 1560),
            headerCell("Win Rate", 1560), headerCell("Trades", 1560),
            headerCell("Strategy", 2340)
          ]}),
          new TableRow({ children: [
            dataCell("Politics", 2340, { bold: true }), dataCell("3 (High)", 1560),
            dataCell("~70%+", 1560, { color: GREEN }), dataCell("Active", 1560),
            dataCell("Full position sizing", 2340)
          ]}),
          new TableRow({ children: [
            dataCell("Weather", 2340, { bold: true }), dataCell("3 (High)", 1560),
            dataCell("NOAA-backed", 1560, { color: GREEN }), dataCell("0*", 1560),
            dataCell("NOAA arbitrage overlay", 2340)
          ]}),
          new TableRow({ children: [
            dataCell("Economic", 2340, { bold: true }), dataCell("2 (Medium)", 1560),
            dataCell("~65%", 1560), dataCell("Active", 1560),
            dataCell("Full position sizing", 2340)
          ]}),
          new TableRow({ children: [
            dataCell("Geopolitical", 2340, { bold: true }), dataCell("1 (Low)", 1560),
            dataCell("~55%", 1560, { color: YELLOW }), dataCell("Active", 1560),
            dataCell("50% reduced sizing", 2340)
          ]}),
          new TableRow({ children: [
            dataCell("Crypto / Sports", 2340), dataCell("0 (Skip)", 1560),
            dataCell("N/A", 1560, { color: MED_GRAY }), dataCell("Skipped", 1560),
            dataCell("Zero LLM edge per research", 2340)
          ]}),
        ]
      }),
      bodyText("* No active weather markets detected during March. NOAA 6-city pipeline operational and awaiting opportunities.", { before: 60 }),

      // ── MARKET COMMENTARY ──
      sectionHeading("Market Commentary"),
      bodyText(
        "March 2026 marked the fund\u2019s entry into paper trading on Polymarket. The prediction market ecosystem continued to grow, with Polymarket maintaining its position as the dominant CLOB-based platform. Key developments this month included the ongoing impact of taker fees introduced in February 2026, which have reshaped the competitive landscape by penalizing pure taker strategies and favoring market makers."
      ),
      bodyText(
        "Political markets remain the fund\u2019s primary edge category, consistent with academic research showing LLMs perform best in political forecasting. The competitive environment intensified, with open-source bot frameworks proliferating on GitHub and reports of institutional interest (Susquehanna hiring prediction market traders). Our differentiated approach\u2014AI forecasting rather than mechanical arbitrage\u2014remains our thesis, though it requires live validation."
      ),

      // ── RISK METRICS ──
      sectionHeading("Risk Metrics"),

      new Table({
        width: { size: CONTENT_W, type: WidthType.DXA },
        columnWidths: [4680, 4680],
        rows: [
          new TableRow({ children: [headerCell("Metric", 4680), headerCell("Value", 4680)] }),
          new TableRow({ children: [dataCell("Max Drawdown (backtest)", 4680), dataCell("$50.00 / 66.7% of capital", 4680)] }),
          new TableRow({ children: [dataCell("Sharpe-Equivalent (backtest)", 4680), dataCell("0.64 (Quarter-Kelly)", 4680)] }),
          new TableRow({ children: [dataCell("Brier Score", 4680), dataCell("0.239 (random = 0.25)", 4680)] }),
          new TableRow({ children: [dataCell("Current Exposure", 4680), dataCell("$68.00 / $75.00 (90.7%)", 4680, { color: YELLOW })] }),
          new TableRow({ children: [dataCell("Position Concentration", 4680), dataCell("34 positions \u00D7 $2 (diversified)", 4680)] }),
          new TableRow({ children: [dataCell("Monte Carlo P(Total Loss)", 4680), dataCell("0.0% (10,000 sims)", 4680, { color: GREEN })] }),
          new TableRow({ children: [dataCell("Capital Utilization", 4680), dataCell("90.7% deployed", 4680)] }),
        ]
      }),

      bodyText(
        "Capital utilization is high (90.7%) given small fund size ($75). Kelly criterion integration (quarter-Kelly sizing) is pending, which will dynamically size positions based on edge magnitude rather than flat $2 sizing. This will improve risk-adjusted returns."
      ),

      // Page break
      new Paragraph({ children: [new PageBreak()] }),

      // ── OUTLOOK ──
      sectionHeading("Outlook \u2014 April 2026"),

      bodyText("Key priorities for next month:", { after: 40 }),

      new Paragraph({
        numbering: { reference: "bullets", level: 0 },
        spacing: { before: 40, after: 40 },
        children: [new TextRun({ text: "Accumulate resolved trade data: Target 50+ resolved positions to validate backtest win rate against live paper results.", font: "Arial", size: 19, color: DARK_GRAY })]
      }),
      new Paragraph({
        numbering: { reference: "bullets", level: 0 },
        spacing: { before: 40, after: 40 },
        children: [new TextRun({ text: "Integrate Kelly criterion sizing: Replace flat $2 with quarter-Kelly for improved risk-adjusted returns (+40\u201380% projected ARR impact).", font: "Arial", size: 19, color: DARK_GRAY })]
      }),
      new Paragraph({
        numbering: { reference: "bullets", level: 0 },
        spacing: { before: 40, after: 40 },
        children: [new TextRun({ text: "Combined backtest re-run: Execute full backtest with all improvements (calibration + asymmetric thresholds + category routing + taker fees).", font: "Arial", size: 19, color: DARK_GRAY })]
      }),
      new Paragraph({
        numbering: { reference: "bullets", level: 0 },
        spacing: { before: 40, after: 40 },
        children: [new TextRun({ text: "Evaluate live trading switch: If paper win rate exceeds 55% over 2 weeks of resolved trades, prepare for live capital deployment.", font: "Arial", size: 19, color: DARK_GRAY })]
      }),
      new Paragraph({
        numbering: { reference: "bullets", level: 0 },
        spacing: { before: 40, after: 40 },
        children: [new TextRun({ text: "News sentiment pipeline: Begin integrating NewsData.io or Finnhub for real-time context to improve Claude\u2019s probability estimates.", font: "Arial", size: 19, color: DARK_GRAY })]
      }),

      bodyText(
        "The fund remains in validation phase. No investor capital will be called until live trading demonstrates consistent performance matching or exceeding backtest projections.",
        { before: 100 }
      ),

      // ── APPENDIX ──
      new Paragraph({ children: [new PageBreak()] }),
      sectionHeading("Appendix: Paper Trade Log"),
      label("All 34 open paper positions as of March 5, 2026. $2.00 per position, flat sizing."),

      // Trade log table
      (() => {
        const trades = [
          ["1", "Will Trump sign executive order on crypto by April?", "NO", "$0.35", "Open"],
          ["2", "Fed rate cut in March 2026?", "NO", "$0.82", "Open"],
          ["3", "Ukraine ceasefire agreement by April 2026?", "NO", "$0.25", "Open"],
          ["4", "Bitcoin above $100K on March 31?", "NO", "$0.45", "Open"],
          ["5", "Will AI regulation bill pass Senate by June?", "YES", "$0.38", "Open"],
          ["6", "US GDP Q1 2026 above 2.5%?", "NO", "$0.55", "Open"],
          ["7", "El Ni\u00F1o declared by NOAA in 2026?", "YES", "$0.42", "Open"],
          ["8", "Will Starship reach orbit by April?", "NO", "$0.30", "Open"],
          ["9", "Fed Chair Powell reappointed?", "NO", "$0.70", "Open"],
          ["10", "CA wildfire state of emergency March?", "NO", "$0.15", "Open"],
          ["11\u201334", "(24 additional positions across politics, economics, geopolitical)", "\u2014", "Various", "Open"],
        ];

        const colW = [600, 3700, 900, 1200, 960];
        // Ensure columns sum to 9360: 600+3700+900+1200+960 = 7360... let me fix
        // CONTENT_W = 9360
        const cw = [700, 4260, 1200, 1400, 1800];

        return new Table({
          width: { size: CONTENT_W, type: WidthType.DXA },
          columnWidths: cw,
          rows: [
            new TableRow({ children: [
              headerCell("#", cw[0]), headerCell("Market", cw[1]), headerCell("Side", cw[2]),
              headerCell("Entry", cw[3]), headerCell("Status", cw[4])
            ]}),
            ...trades.map(t => new TableRow({ children: [
              dataCell(t[0], cw[0], { size: 16 }),
              dataCell(t[1], cw[1], { size: 16 }),
              dataCell(t[2], cw[2], { size: 16, bold: true, color: t[2] === "NO" ? ACCENT_BLUE : GREEN }),
              dataCell(t[3], cw[3], { size: 16 }),
              dataCell(t[4], cw[4], { size: 16, color: YELLOW }),
            ]}))
          ]
        });
      })(),

      // Disclaimer
      new Paragraph({ spacing: { before: 300, after: 0 } }),
      new Paragraph({
        spacing: { before: 0, after: 60 },
        border: { top: { style: BorderStyle.SINGLE, size: 2, color: "CCCCCC", space: 4 } },
        children: [new TextRun({
          text: "DISCLAIMER: ",
          font: "Arial", size: 14, bold: true, color: MED_GRAY
        }), new TextRun({
          text: "This report is for informational purposes only and does not constitute an offer to sell or solicitation to buy securities. All performance figures are based on paper trading and backtested results and do not represent actual trading with live capital. Past performance, whether simulated or actual, does not guarantee future results. Prediction market trading involves substantial risk of loss. This is a speculative investment \u2014 only invest money you can afford to lose entirely.",
          font: "Arial", size: 14, color: MED_GRAY, italics: true
        })]
      }),
      new Paragraph({
        spacing: { before: 60, after: 0 },
        alignment: AlignmentType.CENTER,
        children: [new TextRun({
          text: "Predictive Alpha Fund  |  Contact: johnhavenbradley@gmail.com",
          font: "Arial", size: 14, color: MED_GRAY
        })]
      }),
    ]
  }]
});

// ── Write ──
Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("/sessions/dazzling-funny-gauss/mnt/Quant/Monthly_Report_March_2026.docx", buffer);
  console.log("Monthly report created successfully.");
});
