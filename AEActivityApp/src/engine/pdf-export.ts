import type { AEScore, ScoringDimension, CalendarEvent, ExportOptions, AEProfile, Activity } from '../types'

function getTierBadge(score: number): { label: string; color: [number, number, number] } {
  if (score >= 90) return { label: 'Platinum', color: [11, 100, 221] }
  if (score >= 75) return { label: 'Gold', color: [254, 197, 20] }
  if (score >= 60) return { label: 'Silver', color: [152, 162, 179] }
  if (score >= 40) return { label: 'Bronze', color: [240, 78, 152] }
  return { label: 'Developing', color: [208, 213, 221] }
}

function addFooter(doc: any, pageWidth: number, pageHeight: number, dateStr: string): void {
  doc.setDrawColor(208, 213, 221)
  doc.setLineWidth(0.5)
  doc.line(40, pageHeight - 40, pageWidth - 40, pageHeight - 40)
  doc.setFontSize(7)
  doc.setTextColor(152, 162, 179)
  doc.text('Elastic AE Scorecard', 40, pageHeight - 28)
  doc.text(`Generated ${dateStr}`, pageWidth / 2, pageHeight - 28, { align: 'center' })
  doc.text('Confidential', pageWidth - 40, pageHeight - 28, { align: 'right' })
}

export async function exportToPDF(
  scores: AEScore[],
  dimensions: ScoringDimension[],
  events: CalendarEvent[],
  options: ExportOptions
): Promise<Blob> {
  const { jsPDF } = await import('jspdf')
  await import('jspdf-autotable')

  const doc = new jsPDF({ orientation: 'landscape', unit: 'pt', format: 'letter' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const dateStr = new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })

  // Title page
  doc.setFillColor(11, 100, 221)
  doc.rect(0, 0, pageWidth, pageHeight, 'F')
  doc.setTextColor(255, 255, 255)
  doc.setFontSize(32)
  doc.text(options.title, pageWidth / 2, pageHeight / 2 - 40, { align: 'center' })
  if (options.subtitle) {
    doc.setFontSize(16)
    doc.text(options.subtitle, pageWidth / 2, pageHeight / 2 + 10, { align: 'center' })
  }
  doc.setFontSize(12)
  doc.text(options.period, pageWidth / 2, pageHeight / 2 + 50, { align: 'center' })

  // Leaderboard page
  doc.addPage()
  doc.setTextColor(52, 55, 65)
  doc.setFontSize(20)
  doc.text('AE Activity Leaderboard', 40, 50)
  doc.setFontSize(10)
  doc.text(`Period: ${options.period}`, 40, 70)

  const tableHead = [['Rank', 'Name', 'Region', 'Territory', 'Score', 'Tier', 'Trend']]
  const tableBody = scores.map((s) => {
    const tier = getTierBadge(s.totalScore)
    return [
      `#${s.rank}`,
      s.aeName,
      s.region,
      s.territory,
      `${s.totalScore}`,
      tier.label,
      s.trend === 'up' ? 'Rising' : s.trend === 'down' ? 'Falling' : 'Stable',
    ]
  })

  ;(doc as any).autoTable({
    startY: 85,
    head: tableHead,
    body: tableBody,
    theme: 'grid',
    headStyles: { fillColor: [11, 100, 221], textColor: 255, fontSize: 10 },
    bodyStyles: { fontSize: 9 },
    alternateRowStyles: { fillColor: [245, 247, 250] },
    margin: { left: 40, right: 40 },
  })
  addFooter(doc, pageWidth, pageHeight, dateStr)

  // Dimension breakdown page
  if (options.includeDetails && dimensions.length > 0) {
    doc.addPage()
    doc.setTextColor(52, 55, 65)
    doc.setFontSize(20)
    doc.text('Scoring Dimensions', 40, 50)

    const dimHead = [['Dimension', 'Weight', 'Description']]
    const dimBody = dimensions.map((d) => [d.name, `${d.weight}%`, d.description])

    ;(doc as any).autoTable({
      startY: 70,
      head: dimHead,
      body: dimBody,
      theme: 'grid',
      headStyles: { fillColor: [11, 100, 221], textColor: 255, fontSize: 10 },
      bodyStyles: { fontSize: 9 },
      margin: { left: 40, right: 40 },
    })

    // Per-AE dimension scores
    const detailHead = [['Name', ...dimensions.map((d) => d.name), 'Total']]
    const detailBody = scores.map((s) => [
      s.aeName,
      ...dimensions.map((d) => `${s.dimensionScores[d.id] ?? 0}`),
      `${s.totalScore}`,
    ])

    ;(doc as any).autoTable({
      startY: (doc as any).lastAutoTable.finalY + 30,
      head: detailHead,
      body: detailBody,
      theme: 'grid',
      headStyles: { fillColor: [21, 51, 133], textColor: 255, fontSize: 8 },
      bodyStyles: { fontSize: 8 },
      alternateRowStyles: { fillColor: [245, 247, 250] },
      margin: { left: 40, right: 40 },
    })
    addFooter(doc, pageWidth, pageHeight, dateStr)
  }

  // Upcoming calendar page
  if (events.length > 0) {
    doc.addPage()
    doc.setTextColor(52, 55, 65)
    doc.setFontSize(20)
    doc.text('Upcoming Calendar', 40, 50)

    const calHead = [['Date', 'Event', 'Type', 'Attendees']]
    const calBody = events.slice(0, 15).map((e) => [
      e.date,
      e.title,
      e.type.replace(/_/g, ' '),
      (e.attendees ?? []).join(', '),
    ])

    ;(doc as any).autoTable({
      startY: 70,
      head: calHead,
      body: calBody,
      theme: 'grid',
      headStyles: { fillColor: [11, 100, 221], textColor: 255, fontSize: 10 },
      bodyStyles: { fontSize: 8 },
      alternateRowStyles: { fillColor: [245, 247, 250] },
      margin: { left: 40, right: 40 },
    })
    addFooter(doc, pageWidth, pageHeight, dateStr)
  }

  return doc.output('blob')
}

export async function exportSingleAEPDF(
  ae: AEProfile,
  score: AEScore,
  dimensions: ScoringDimension[],
  activities: Activity[],
  events: CalendarEvent[],
  quarter: string
): Promise<Blob> {
  const { jsPDF } = await import('jspdf')
  await import('jspdf-autotable')

  const doc = new jsPDF({ orientation: 'portrait', unit: 'pt', format: 'letter' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const dateStr = new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })
  const tier = getTierBadge(score.totalScore)

  // Page 1: AE header with score gauge and tier badge
  doc.setFillColor(11, 100, 221)
  doc.rect(0, 0, pageWidth, 160, 'F')
  doc.setTextColor(255, 255, 255)
  doc.setFontSize(24)
  doc.text(ae.name, 40, 55)
  doc.setFontSize(11)
  doc.text(`${ae.team} | ${ae.region} | ${ae.territory}`, 40, 78)
  doc.text(quarter, 40, 96)

  // Score gauge (large number on the right)
  doc.setFontSize(64)
  doc.text(`${score.totalScore}`, pageWidth - 60, 80, { align: 'right' })
  doc.setFontSize(14)
  doc.text(tier.label, pageWidth - 60, 105, { align: 'right' })
  doc.setFontSize(10)
  const trendLabel = score.trend === 'up' ? 'Trending Up' : score.trend === 'down' ? 'Trending Down' : 'Stable'
  doc.text(`Rank #${score.rank} | ${trendLabel}`, pageWidth - 60, 125, { align: 'right' })

  // Dimension breakdown table
  doc.setTextColor(52, 55, 65)
  doc.setFontSize(16)
  doc.text('Dimension Breakdown', 40, 195)

  const dimHead = [['Dimension', 'Score', 'Weight', 'Weighted Contribution']]
  const dimBody = dimensions.map((d) => {
    const dimScore = score.dimensionScores[d.id] ?? 0
    const totalWeight = dimensions.reduce((s, dd) => s + dd.weight, 0)
    const contribution = Math.round(dimScore * (d.weight / totalWeight))
    return [d.name, `${dimScore}`, `${d.weight}%`, `${contribution}`]
  })

  ;(doc as any).autoTable({
    startY: 210,
    head: dimHead,
    body: dimBody,
    theme: 'grid',
    headStyles: { fillColor: [11, 100, 221], textColor: 255, fontSize: 10 },
    bodyStyles: { fontSize: 10 },
    alternateRowStyles: { fillColor: [245, 247, 250] },
    margin: { left: 40, right: 40 },
    columnStyles: {
      1: { halign: 'center' },
      2: { halign: 'center' },
      3: { halign: 'center' },
    },
  })

  // Activity summary on page 1
  const afterDimY = (doc as any).lastAutoTable.finalY + 25
  doc.setFontSize(16)
  doc.text('Activity Summary', 40, afterDimY)

  const aeActivities = activities.filter((a) => a.aeId === ae.id)
  const activityCounts = new Map<string, number>()
  for (const a of aeActivities) {
    activityCounts.set(a.type, (activityCounts.get(a.type) ?? 0) + 1)
  }

  const actHead = [['Activity Type', 'Count']]
  const actBody = Array.from(activityCounts.entries()).map(([type, count]) => [
    type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
    `${count}`,
  ])

  ;(doc as any).autoTable({
    startY: afterDimY + 15,
    head: actHead,
    body: actBody,
    theme: 'grid',
    headStyles: { fillColor: [21, 51, 133], textColor: 255, fontSize: 9 },
    bodyStyles: { fontSize: 9 },
    alternateRowStyles: { fillColor: [245, 247, 250] },
    margin: { left: 40, right: 40 },
    tableWidth: 300,
  })

  addFooter(doc, pageWidth, pageHeight, dateStr)

  // Page 2: Activity detail log
  doc.addPage()
  doc.setTextColor(52, 55, 65)
  doc.setFontSize(16)
  doc.text(`Activity Log: ${ae.name}`, 40, 50)

  if (aeActivities.length > 0) {
    const logHead = [['Date', 'Type', 'Description', 'Deal', 'ACV']]
    const logBody = aeActivities
      .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())
      .map((a) => [
        a.date,
        a.type.replace(/_/g, ' '),
        a.description.length > 50 ? a.description.slice(0, 47) + '...' : a.description,
        a.dealName ?? '-',
        a.acv ? `$${(a.acv / 1000).toFixed(0)}K` : '-',
      ])

    ;(doc as any).autoTable({
      startY: 65,
      head: logHead,
      body: logBody,
      theme: 'grid',
      headStyles: { fillColor: [11, 100, 221], textColor: 255, fontSize: 9 },
      bodyStyles: { fontSize: 8 },
      alternateRowStyles: { fillColor: [245, 247, 250] },
      margin: { left: 40, right: 40 },
      columnStyles: {
        4: { halign: 'right' },
      },
    })
  } else {
    doc.setFontSize(11)
    doc.text('No activities recorded for this period.', 40, 80)
  }

  // Upcoming events for this AE
  const aeEvents = events.filter((e) => e.aeId === ae.id)
  if (aeEvents.length > 0) {
    const evtStartY = aeActivities.length > 0 ? (doc as any).lastAutoTable.finalY + 30 : 110
    doc.setFontSize(14)
    doc.text('Upcoming Events', 40, evtStartY)

    const evtHead = [['Date', 'Event', 'Type', 'Attendees']]
    const evtBody = aeEvents.map((e) => [
      e.date,
      e.title,
      e.type.replace(/_/g, ' '),
      (e.attendees ?? []).join(', '),
    ])

    ;(doc as any).autoTable({
      startY: evtStartY + 15,
      head: evtHead,
      body: evtBody,
      theme: 'grid',
      headStyles: { fillColor: [72, 239, 207], textColor: [52, 55, 65], fontSize: 9 },
      bodyStyles: { fontSize: 8 },
      margin: { left: 40, right: 40 },
    })
  }

  addFooter(doc, pageWidth, pageHeight, dateStr)

  return doc.output('blob')
}

export async function exportBatchPDFs(
  aes: AEProfile[],
  scores: AEScore[],
  dimensions: ScoringDimension[],
  activities: Activity[],
  events: CalendarEvent[],
  quarter: string
): Promise<Blob> {
  // Build individual PDFs and bundle into a ZIP
  const { default: JSZip } = await import('jszip')

  const zip = new JSZip()

  for (const ae of aes) {
    const score = scores.find((s) => s.aeId === ae.id)
    if (!score) continue

    const pdfBlob = await exportSingleAEPDF(ae, score, dimensions, activities, events, quarter)
    const safeName = ae.name.replace(/\s+/g, '_')
    zip.file(`AE_Scorecard_${safeName}_${quarter}.pdf`, pdfBlob)
  }

  return zip.generateAsync({ type: 'blob' })
}
