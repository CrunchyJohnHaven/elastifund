import type { AEScore, ScoringDimension, CalendarEvent, ExportOptions } from '../types'

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

  const tableHead = [['Rank', 'Name', 'Region', 'Territory', 'Score', 'Trend']]
  const tableBody = scores.map((s) => [
    `#${s.rank}`,
    s.aeName,
    s.region,
    s.territory,
    `${s.totalScore}`,
    s.trend === 'up' ? 'Rising' : s.trend === 'down' ? 'Falling' : 'Stable',
  ])

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

  // Dimension breakdown page
  if (options.includeDetails && dimensions.length > 0) {
    doc.addPage()
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
  }

  // Upcoming calendar page
  if (events.length > 0) {
    doc.addPage()
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
  }

  return doc.output('blob')
}
