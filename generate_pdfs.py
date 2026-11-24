import os
from pathlib import Path
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
)
from reportlab.pdfgen import canvas

STATIC_DIR = Path("app/static")
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Color Palette
DARK_PINE = colors.HexColor("#0f3d32")
MID_PINE = colors.HexColor("#165b4c")
EMERALD = colors.HexColor("#10b981")
MINT = colors.HexColor("#ecfdf5")
LIME = colors.HexColor("#e2f752")
DEEP_DARK = colors.HexColor("#091e19")
TEXT_DARK = colors.HexColor("#0f172a")
TEXT_MUTED = colors.HexColor("#475569")
BORDER_LIGHT = colors.HexColor("#e2e8f0")
WHITE = colors.HexColor("#ffffff")
BLUE_BG = colors.HexColor("#eff6ff")
BLUE_TEXT = colors.HexColor("#1d4ed8")
AMBER_BG = colors.HexColor("#fffbeb")
AMBER_TEXT = colors.HexColor("#b45309")
ROSE_BG = colors.HexColor("#fff1f2")
ROSE_TEXT = colors.HexColor("#be123c")


class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        # Top banner line
        self.setFillColor(DARK_PINE)
        self.rect(0, 580, 842, 15, fill=True, stroke=False)
        self.setFillColor(LIME)
        self.rect(0, 577, 842, 3, fill=True, stroke=False)
        
        # Bottom footer bar
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(TEXT_MUTED)
        self.drawString(36, 18, "TrimTime · The Win-Win Salon Queue & Operating System")
        page_text = f"Slide {self._pageNumber} of {page_count}"
        self.drawRightString(806, 18, page_text)
        self.setStrokeColor(BORDER_LIGHT)
        self.setLineWidth(0.8)
        self.line(36, 28, 806, 28)
        self.restoreState()


def build_presentation_pdf(output_path: Path):
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=landscape(A4),  # 842 x 595 pt
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        "SlideTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=26,
        leading=32,
        textColor=DEEP_DARK,
        spaceAfter=10,
    )
    
    subtitle_style = ParagraphStyle(
        "SlideSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=12,
        leading=16,
        textColor=TEXT_MUTED,
        spaceAfter=18,
    )
    
    badge_style = ParagraphStyle(
        "SlideBadge",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=MID_PINE,
        spaceAfter=6,
    )
    
    card_title_style = ParagraphStyle(
        "CardTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=DEEP_DARK,
        spaceAfter=6,
    )

    card_body_style = ParagraphStyle(
        "CardBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=TEXT_MUTED,
    )

    story = []

    # ==========================================
    # SLIDE 1: Cover
    # ==========================================
    story.append(Paragraph("TRIMTIME · SALON & BARBER OPERATING SYSTEM", badge_style))
    story.append(Spacer(1, 15))
    story.append(Paragraph("Your Salon is Full.<br/><font color='#10b981'>Why Are You Still Losing Money?</font>", ParagraphStyle(
        "CoverTitle", fontName="Helvetica-Bold", fontSize=34, leading=40, textColor=DEEP_DARK, spaceAfter=14
    )))
    story.append(Paragraph("How live virtual queues stop walk-away losses, monetize idle chair gaps, and eliminate waiting room chaos for customers.", subtitle_style))
    story.append(Spacer(1, 20))

    t1_data = [
        [
            Paragraph("<b>FOR SALON OWNERS</b><br/><br/>• +₹30,000–₹60,000 added profit/month<br/>• Stops 30% weekend walk-in loss<br/>• Fills dead 20-min gaps between bookings<br/>• Zero scissors-in-hand phone chaos", card_body_style),
            Paragraph("<b>FOR CUSTOMERS</b><br/><br/>• 0 minutes wasted on waiting sofa<br/>• Live minute-by-minute mobile clock<br/>• Freedom to relax at home or grab coffee<br/>• 1-tap 6-digit MPIN login", card_body_style),
            Paragraph("<b>DUAL-SIDED TECH</b><br/><br/>• Simple QR scan at entrance (No app install)<br/>• Real-time WebSocket synchronization<br/>• Unisex, Men & Women categorization<br/>• Automated stylist ratings & analytics", card_body_style),
        ]
    ]
    t1 = Table(t1_data, colWidths=[250, 250, 250])
    t1.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), MINT),
        ("BACKGROUND", (1, 0), (1, 0), BLUE_BG),
        ("BACKGROUND", (2, 0), (2, 0), AMBER_BG),
        ("BOX", (0, 0), (-1, -1), 1, BORDER_LIGHT),
        ("INNERGRID", (0, 0), (-1, -1), 8, WHITE),
        ("TOPPADDING", (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
    ]))
    story.append(t1)
    story.append(PageBreak())

    # ==========================================
    # SLIDE 2: The Two Big Problems
    # ==========================================
    story.append(Paragraph("01 · THE PROBLEM", badge_style))
    story.append(Paragraph("Two Sides of the Same Door. Both Losing.", title_style))
    story.append(Paragraph("Traditional salons bleed revenue while customers suffer through archaic queueing on peak days.", subtitle_style))

    t2_data = [
        [
            Paragraph("<b>SALON OWNER NIGHTMARE</b><br/><br/>"
                      "<b>1. The 30% Walk-Away Bleed:</b> On peak weekends, 4–8 potential customers peek in, see a packed waiting bench, and walk away to a competitor.<br/><br/>"
                      "<b>2. Dead 20–30 Minute Chair Gaps:</b> Appointment A ends at 10:30 AM. Next appointment is at 11:00 AM. 30 minutes sit empty. Barber earns ₹0.<br/><br/>"
                      "<b>3. Phone Call Interruption:</b> Answering calls with scissors in wet hands to scribble appointments in messy paper registers.", card_body_style),
            Paragraph("<b>CUSTOMER FRUSTRATION</b><br/><br/>"
                      "<b>1. Zero Wait Time Clarity:</b> 'Bhaiya kitna time lagega?' The barber says 'Bas 10 minute', which turns into 50 painful minutes.<br/><br/>"
                      "<b>2. Trapped on a Cramped Sofa:</b> Customers cannot leave to grab a tea or run errands because they might lose their turn.<br/><br/>"
                      "<b>3. Awkward Visits:</b> Walking into a male-only or ladies-only salon without knowing categories upfront.", card_body_style),
        ]
    ]
    t2 = Table(t2_data, colWidths=[375, 375])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), ROSE_BG),
        ("BACKGROUND", (1, 0), (1, 0), AMBER_BG),
        ("BOX", (0, 0), (-1, -1), 1, BORDER_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 18),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
        ("LEFTPADDING", (0, 0), (-1, -1), 18),
        ("RIGHTPADDING", (0, 0), (-1, -1), 18),
    ]))
    story.append(t2)
    story.append(PageBreak())

    # ==========================================
    # SLIDE 3: The Platform Solution
    # ==========================================
    story.append(Paragraph("02 · THE SOLUTION", badge_style))
    story.append(Paragraph("One Smart QR Code. Total Operating System.", title_style))
    story.append(Paragraph("Zero app download required. Opens instantly in any phone browser (Chrome/Safari) with live sync.", subtitle_style))

    t3_data = [
        [
            Paragraph("<b>1. Live QR Virtual Queue</b><br/><br/>Customers scan the counter QR, choose services, and follow minute-by-minute wait times from anywhere.", card_body_style),
            Paragraph("<b>2. Smart Gap Monetizer</b><br/><br/>System detects 20–30 min gaps between appointments and automatically surfaces quick walk-ins to fill chairs.", card_body_style),
            Paragraph("<b>3. Fast 6-Digit MPIN</b><br/><br/>Instant 1-tap sign-in on trusted devices. No forgotten passwords or SMS OTP delays for customers or barbers.", card_body_style),
        ],
        [
            Paragraph("<b>4. Shop Categories</b><br/><br/>Clear badges for 🚻 Unisex, 💈 Men & Gents, and 💇‍♀️ Women & Ladies with 1-tap customer filtering.", card_body_style),
            Paragraph("<b>5. Multi-Staff Dashboard</b><br/><br/>Barber claim-and-start chair actions, walk-in token generator, and real-time chair status.", card_body_style),
            Paragraph("<b>6. Revenue & Rating Analytics</b><br/><br/>Track daily cuts, revenue per barber, customer satisfaction ratings, and peak hours from any device.", card_body_style),
        ]
    ]
    t3 = Table(t3_data, colWidths=[250, 250, 250])
    t3.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("BOX", (0, 0), (-1, -1), 1, BORDER_LIGHT),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.append(t3)
    story.append(PageBreak())

    # ==========================================
    # SLIDE 4: Value for Salon Owners
    # ==========================================
    story.append(Paragraph("03 · SALON OWNER ROI", badge_style))
    story.append(Paragraph("Turning Lost Minutes into Cash (+₹45k–₹75k/Month)", title_style))
    story.append(Paragraph("Calculated financial gains for a typical 3-chair salon using TrimTime:", subtitle_style))

    t4_data = [
        ["Revenue Driver", "Without TrimTime", "With TrimTime", "Monthly Profit Impact"],
        ["Walk-Away Recovery", "4 walk-ins lost/day (₹250 avg)", "Zero walkaways; tickets tracked", "+ ₹30,000 / month"],
        ["Dead Gap Monetization", "2 empty 25-min gaps/day/chair", "Short beard trims/cuts fitted", "+ ₹18,000 / month"],
        ["No-Show Reduction", "20% phone booking no-shows", "Cut to <5% via live reminder alerts", "+ ₹12,000 / month"],
        ["Total Extra Monthly Revenue", "—", "—", "+ ₹60,000 / month"]
    ]
    t4 = Table(t4_data, colWidths=[180, 190, 200, 180])
    t4.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK_PINE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 1), (-1, 1), WHITE),
        ("BACKGROUND", (0, 2), (-1, 2), MINT),
        ("BACKGROUND", (0, 3), (-1, 3), WHITE),
        ("BACKGROUND", (0, 4), (-1, 4), LIME),
        ("TEXTCOLOR", (0, 4), (-1, 4), DEEP_DARK),
        ("FONTNAME", (0, 4), (-1, 4), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(t4)
    story.append(Spacer(1, 15))
    story.append(Paragraph("<b>The Pitch Rule:</b> Saving just ONE haircut customer every two days pays for the system 10x over.", card_title_style))
    story.append(PageBreak())

    # ==========================================
    # SLIDE 5: Value for Customers
    # ==========================================
    story.append(Paragraph("04 · CUSTOMER DELIGHT", badge_style))
    story.append(Paragraph("Skip the Waiting Room. Keep Every Minute.", title_style))
    story.append(Paragraph("Customers save an average of 38 minutes per salon visit with frictionless mobile tracking.", subtitle_style))

    t5_data = [
        [
            Paragraph("<b>⏱️ Real-Time Wait Clock</b><br/><br/>Phone shows exact queue position: '2 people ahead (~18 min)'. Updates live minute-by-minute.", card_body_style),
            Paragraph("<b>☕ Freedom to Roam</b><br/><br/>Relax at home, grab coffee, or shop nearby. Return only when notified that your turn is next.", card_body_style),
        ],
        [
            Paragraph("<b>🔐 1-Tap 6-Digit MPIN</b><br/><br/>Instant login in 2 seconds. No typing passwords or waiting for SMS codes on your trusted device.", card_body_style),
            Paragraph("<b>🚻 Category & Stylist Choice</b><br/><br/>Pick Unisex, Men or Women. Choose your favourite barber or 'Any available' for fastest service.", card_body_style),
        ]
    ]
    t5 = Table(t5_data, colWidths=[375, 375])
    t5.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("BOX", (0, 0), (-1, -1), 1, BORDER_LIGHT),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
    ]))
    story.append(t5)
    story.append(Spacer(1, 15))
    story.append(Paragraph("<i>'I used to hate Sunday haircut waiting. Now I join the queue from home, walk in when it says 5 minutes left, and sit straight in the chair!'</i> — Rohit S., Verified Customer", card_body_style))
    story.append(PageBreak())

    # ==========================================
    # SLIDE 6: The 25-Min Gap Monetizer
    # ==========================================
    story.append(Paragraph("05 · INNOVATION", badge_style))
    story.append(Paragraph("How We Monetize the Dead 25-Minute Chair Gap", title_style))
    story.append(Paragraph("Appointments are great, but the 20–30 min idle gap between them is lost cash. TrimTime solves this automatically:", subtitle_style))

    gap_data = [
        ["10:30 AM (Current Cut Ends)", "⚡ 25-MINUTE USABLE GAP WINDOW", "11:00 AM (Next Appointment)"],
        [
            Paragraph("<b>Previous Cut Completed</b><br/>Barber marks cut complete. Chair is wiped down (5 min buffer).", card_body_style),
            Paragraph("<b>⚡ FITS OPEN CHAIR GAP</b><br/><br/>TrimTime algorithm identifies that a 15-min Beard Trim or Quick Cut fits before 11:00 AM. <b>Badged in queue for instant claim! (+₹150)</b>", card_body_style),
            Paragraph("<b>Next Booked Appointment</b><br/>Customer arrives on time. Zero overlap or delay.", card_body_style)
        ]
    ]
    t6 = Table(gap_data, colWidths=[240, 270, 240])
    t6.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), TEXT_MUTED),
        ("BACKGROUND", (1, 0), (1, 0), LIME),
        ("BACKGROUND", (2, 0), (2, 0), DARK_PINE),
        ("TEXTCOLOR", (0, 0), (0, 0), WHITE),
        ("TEXTCOLOR", (1, 0), (1, 0), DEEP_DARK),
        ("TEXTCOLOR", (2, 0), (2, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("BACKGROUND", (0, 1), (-1, 1), WHITE),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(t6)
    story.append(Spacer(1, 15))
    story.append(Paragraph("<b>Result:</b> Barbers never sit idle, chairs are 100% productive, and walk-in customers get served in record time.", card_body_style))
    story.append(PageBreak())

    # ==========================================
    # SLIDE 7: 3-Step Simple Flow
    # ==========================================
    story.append(Paragraph("06 · EFFORTLESS FLOW", badge_style))
    story.append(Paragraph("So Simple, Anyone Can Use It in 5 Seconds", title_style))
    story.append(Paragraph("If your barbers and customers know how to use WhatsApp, they already know how to use TrimTime.", subtitle_style))

    t7_data = [
        [
            Paragraph("<b>STEP 1: SCAN COUNTER QR</b><br/><br/>Customer scans the shop standee with phone camera. Opens immediately in browser. No app install needed.", card_body_style),
            Paragraph("<b>STEP 2: TRACK ON MOBILE</b><br/><br/>Selects haircut or combo. Receives digital ticket #A03 with live minute-by-minute countdown timer.", card_body_style),
            Paragraph("<b>STEP 3: SIT & GET STYLED</b><br/><br/>Customer walks in when notified. Barber taps 'Start', cuts hair, taps 'Complete'. Digital receipt & review sent.", card_body_style),
        ]
    ]
    t7 = Table(t7_data, colWidths=[250, 250, 250])
    t7.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("BOX", (0, 0), (-1, -1), 1, BORDER_LIGHT),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 18),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
    ]))
    story.append(t7)
    story.append(PageBreak())

    # ==========================================
    # SLIDE 8: 7-Day Pilot & Action
    # ==========================================
    story.append(Paragraph("07 · ZERO RISK TRIAL", badge_style))
    story.append(Paragraph("Try It This Weekend. Pay ₹0.", title_style))
    story.append(Paragraph("We set up your custom QR standee, staff logins, and digital service menu for free.", subtitle_style))

    t8_data = [
        [
            Paragraph("<b>WHAT YOU RECEIVE IN 24 HOURS (FREE):</b><br/><br/>"
                      "✓ <b>1 Custom Acrylic QR Standee</b> for your counter / reception desk<br/>"
                      "✓ <b>Mirror QR Stickers</b> for styling stations<br/>"
                      "✓ <b>Staff & Barber Tablet / Mobile Login accounts</b> with 1-tap MPIN<br/>"
                      "✓ <b>Digital Service Menu</b> with duration & price configuration<br/>"
                      "✓ <b>10-Minute Staff Training</b> by our dedicated onboarding specialist<br/><br/>"
                      "<b>OUR GUARANTEE:</b> If you don't save at least 5 walk-away customers this weekend, you pay nothing.", card_body_style),
            Paragraph("<b>GET STARTED TODAY:</b><br/><br/>"
                      "📞 <b>Phone / WhatsApp:</b> +91 98765 43210<br/><br/>"
                      "🌐 <b>Live Web Demo:</b> trimtime.in / localhost:8000<br/><br/>"
                      "📧 <b>Email:</b> get@trimtime.in<br/><br/>"
                      "<i>Scan the QR code on the visiting card to test the live customer queue right now!</i>", card_body_style)
        ]
    ]
    t8 = Table(t8_data, colWidths=[450, 300])
    t8.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), MINT),
        ("BACKGROUND", (1, 0), (1, 0), WHITE),
        ("BOX", (0, 0), (-1, -1), 1, BORDER_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 18),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
        ("LEFTPADDING", (0, 0), (-1, -1), 18),
        ("RIGHTPADDING", (0, 0), (-1, -1), 18),
    ]))
    story.append(t8)

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Presentation PDF successfully built at: {output_path}")


def build_visiting_card_pdf(output_path: Path):
    from reportlab.lib.pagesizes import inch
    from reportlab.lib import colors
    # Standard business card is 3.5 in x 2.0 in (252 x 144 pt)
    w, h = 3.5 * inch, 2.0 * inch
    c = canvas.Canvas(str(output_path), pagesize=(w, h))

    # ================= PAGE 1: FRONT =================
    # Card Background with rounded corners
    c.setFillColor(colors.HexColor("#0a251e"))
    c.setStrokeColor(colors.HexColor("#165b4c"))
    c.setLineWidth(1)
    c.roundRect(4, 4, w - 8, h - 8, 8, fill=True, stroke=True)

    # Accent glow circle
    c.setFillColor(colors.HexColor("#0f3d32"))
    c.circle(w - 20, h - 20, 45, fill=True, stroke=False)

    # Logo Block: Neon Lime Box with Dark 'T'
    c.setFillColor(LIME)
    c.roundRect(14, h - 34, 20, 20, 4, fill=True, stroke=False)
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(DEEP_DARK)
    c.drawCentredString(24, h - 30, "T")

    # Brand Name
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(WHITE)
    c.drawString(38, h - 24, "TRIM")
    c.setFillColor(LIME)
    c.drawString(67, h - 24, "TIME")

    # Sub-brand
    c.setFont("Helvetica", 5)
    c.setFillColor(colors.HexColor("#a7f3d0"))
    c.drawString(38, h - 31, "SALON QUEUE & CHAIR OS")

    # Top right category badge
    c.setFillColor(colors.HexColor("#165b4c"))
    c.roundRect(w - 88, h - 28, 74, 12, 6, fill=True, stroke=False)
    c.setFont("Helvetica-Bold", 4.8)
    c.setFillColor(colors.HexColor("#ecfdf5"))
    c.drawCentredString(w - 51, h - 24, "Unisex · Men · Women")

    # Center Tagline Headline
    c.setFont("Helvetica-Bold", 10.5)
    c.setFillColor(WHITE)
    c.drawString(14, h - 56, "Skip the waiting room.")
    c.setFillColor(LIME)
    c.drawString(14, h - 69, "Keep every chair full.")

    # Subtitle
    c.setFont("Helvetica", 5.5)
    c.setFillColor(colors.HexColor("#d1fae5"))
    c.drawString(14, h - 80, "Live QR queues · Smart gap monetization · 1-tap MPIN booking")

    # Bottom Divider Line
    c.setStrokeColor(colors.HexColor("#165b4c"))
    c.setLineWidth(0.6)
    c.line(14, 38, w - 14, 38)

    # Bottom Left: Founder Info
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(WHITE)
    c.drawString(14, 26, "Rahul Kumar")
    c.setFont("Helvetica", 5)
    c.setFillColor(colors.HexColor("#a7f3d0"))
    c.drawString(14, 17, "Product & Growth Lead")

    # Bottom Right: Contact Details
    c.setFont("Helvetica-Bold", 5.8)
    c.setFillColor(WHITE)
    c.drawRightString(w - 14, 26, "📞 +91 98765 43210")
    c.setFont("Helvetica", 5)
    c.setFillColor(colors.HexColor("#a7f3d0"))
    c.drawRightString(w - 14, 17, "🌐 trimtime.in · get@trimtime.in")

    c.showPage()

    # ================= PAGE 2: BACK =================
    # Card Background: Clean Luxury Off-White
    c.setFillColor(colors.HexColor("#faf8f5"))
    c.setStrokeColor(colors.HexColor("#e2e8f0"))
    c.setLineWidth(1)
    c.roundRect(4, 4, w - 8, h - 8, 8, fill=True, stroke=True)

    # Top Header
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(DARK_PINE)
    c.drawString(14, h - 18, "WHY TRIMTIME?")

    c.setFillColor(MINT)
    c.setStrokeColor(colors.HexColor("#a7f3d0"))
    c.roundRect(w - 76, h - 21, 62, 11, 5, fill=True, stroke=True)
    c.setFont("Helvetica-Bold", 5)
    c.setFillColor(DARK_PINE)
    c.drawCentredString(w - 45, h - 17.5, "Free 7-Day Pilot")

    # Divider line
    c.setStrokeColor(BORDER_LIGHT)
    c.setLineWidth(0.5)
    c.line(14, h - 25, w - 14, h - 25)

    # Dual Columns: For Salons vs For Customers
    box_w = (w - 36) / 2
    # Left Box: For Salons
    c.setFillColor(WHITE)
    c.roundRect(14, h - 78, box_w, 48, 4, fill=True, stroke=True)
    c.setFont("Helvetica-Bold", 5.5)
    c.setFillColor(DARK_PINE)
    c.drawString(18, h - 35, "💈 FOR SALON OWNERS:")
    c.setFont("Helvetica", 4.8)
    c.setFillColor(TEXT_DARK)
    c.drawString(18, h - 45, "✓ Zero walk-away losses")
    c.drawString(18, h - 54, "✓ Fills 20-min empty gaps")
    c.drawString(18, h - 63, "✓ +₹30k–₹60k monthly profit")
    c.drawString(18, h - 72, "✓ Real-time staff analytics")

    # Right Box: For Customers
    c.setFillColor(WHITE)
    c.roundRect(22 + box_w, h - 78, box_w, 48, 4, fill=True, stroke=True)
    c.setFont("Helvetica-Bold", 5.5)
    c.setFillColor(BLUE_TEXT)
    c.drawString(26 + box_w, h - 35, "👤 FOR CUSTOMERS:")
    c.setFont("Helvetica", 4.8)
    c.setFillColor(TEXT_DARK)
    c.drawString(26 + box_w, h - 45, "✓ Live mobile wait clock")
    c.drawString(26 + box_w, h - 54, "✓ Zero sofa waiting")
    c.drawString(26 + box_w, h - 63, "✓ 1-tap 6-digit MPIN login")
    c.drawString(26 + box_w, h - 72, "✓ Book favourite stylist")

    # Bottom Divider
    c.line(14, 46, w - 14, 46)

    # Bottom QR Code + Video Demo Link
    qr_path = "app/static/demo_qr.png"
    if os.path.exists(qr_path):
        c.drawImage(qr_path, 14, 10, width=32, height=32, preserveAspectRatio=True)

    c.setFont("Helvetica-Bold", 6.2)
    c.setFillColor(TEXT_DARK)
    c.drawString(50, 34, "▶ Scan for Video Demo")
    c.setFont("Helvetica", 4.8)
    c.setFillColor(TEXT_MUTED)
    c.drawString(50, 25, "Watch 60-sec demo on phone")
    c.setFont("Helvetica-Bold", 4.8)
    c.setFillColor(EMERALD)
    c.drawString(50, 16, "trimtime.in/demo")

    # Bottom Right CTA Button
    c.setFillColor(DARK_PINE)
    c.roundRect(w - 74, 12, 60, 24, 4, fill=True, stroke=False)
    c.setFont("Helvetica-Bold", 5.5)
    c.setFillColor(WHITE)
    c.drawCentredString(w - 44, 25, "Watch Demo ▶")
    c.setFont("Helvetica", 4.2)
    c.setFillColor(LIME)
    c.drawCentredString(w - 44, 17, "Book Free Pilot")

    c.showPage()
    c.save()
    print(f"Visiting Card PDF successfully built at: {output_path}")


if __name__ == "__main__":
    build_presentation_pdf(STATIC_DIR / "TrimTime_Presentation.pdf")
    build_visiting_card_pdf(STATIC_DIR / "TrimTime_Visiting_Card.pdf")
