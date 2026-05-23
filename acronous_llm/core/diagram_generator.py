import io
import re
import math
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps


class DiagramGenerator:
    def __init__(self, config):
        self.config = config
        self._init_fonts()
        self._colors = {
            "primary": (108, 92, 231),
            "secondary": (72, 149, 239),
            "accent": (46, 213, 115),
            "warm": (255, 177, 66),
            "danger": (255, 107, 107),
            "purple": (165, 105, 189),
            "teal": (0, 206, 201),
            "pink": (232, 93, 162),
            "bg": (248, 249, 254),
            "text": (55, 55, 75),
            "muted": (140, 140, 160),
            "line": (180, 185, 205),
            "shadow": (0, 0, 0, 30),
        }
        self._palette = [
            (108, 92, 231),
            (72, 149, 239),
            (46, 213, 115),
            (255, 177, 66),
            (255, 107, 107),
            (165, 105, 189),
            (0, 206, 201),
            (232, 93, 162),
        ]

    def _init_fonts(self):
        for size, attr in [(20, "font_large"), (15, "font_med"), (12, "font_small")]:
            try:
                setattr(self, attr, ImageFont.truetype("arial.ttf", size))
            except Exception:
                try:
                    setattr(self, attr, ImageFont.truetype("DejaVuSans.ttf", size))
                except Exception:
                    setattr(self, attr, ImageFont.load_default())

    def _drop_shadow(self, draw, x1, y1, x2, y2, radius=8, offset=4, alpha=40):
        for i in range(offset, offset + 6):
            a = max(0, alpha - i * 5)
            if a <= 0:
                continue
            draw.rounded_rectangle(
                [x1 + i, y1 + i, x2 + i, y2 + i],
                radius=radius, fill=(0, 0, 0, a)
            )

    def _rounded_box_with_gradient(self, draw, x1, y1, x2, y2, color, radius=8):
        r, g, b = color
        steps = 20
        dh = (y2 - y1) / steps
        for i in range(steps):
            t = i / steps
            yr = y1 + dh * i
            yr2 = yr + dh + 1
            fade = 1.0 - t * 0.2
            cr = min(255, int(r * fade))
            cg = min(255, int(g * fade))
            cb = min(255, int(b * fade))
            draw.rounded_rectangle(
                [x1, yr, x2, yr2], radius=radius if 0 < i < steps - 1 else 0,
                fill=(cr, cg, cb)
            )

    def _center_text(self, draw, text, x, y, font, fill="white"):
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((x - tw // 2, y - th // 2), text, fill=fill, font=font)
        except Exception:
            pass

    def generate(self, prompt):
        kw = prompt.lower()

        if "qr" in kw and ("code" in kw or "generate" in kw):
            return self._generate_qr_code(kw)
        if any(w in kw for w in ["binary tree", "bst"]):
            return self._render_binary_tree(kw)
        if any(w in kw for w in ["flowchart", "flow chart", "flow diagram"]):
            return self._render_flowchart(kw)
        if any(w in kw for w in ["linked list", "singly linked", "doubly linked"]):
            return self._render_linked_list(kw)
        if any(w in kw for w in ["stack data", "queue data"]):
            return self._render_stack_queue(kw)
        if any(w in kw for w in ["mind map", "mindmap"]):
            return self._render_mindmap(kw)
        if any(w in kw for w in ["venn", "venn diagram"]):
            return self._render_venn(kw)
        if any(w in kw for w in ["bar chart", "pie chart", "histogram"]):
            return self._render_chart(kw)
        if any(w in kw for w in ["graph", "network", "node", "edge", "vertices"]):
            return self._render_graph(kw)
        if any(w in kw for w in ["architecture", "system design", "microservice"]):
            return self._render_architecture(kw)
        if any(w in kw for w in ["timeline", "sequence diagram"]):
            return self._render_timeline(kw)
        if any(w in kw for w in ["uml", "class diagram"]):
            return self._render_uml(kw)
        return self._render_generic_diagram(kw)

    def _generate_qr_code(self, kw):
        w, h = 500, 500
        url = self._extract_url(kw) or "https://acronous-ai.local"
        text = url.replace("qr code", "").replace("qr", "").replace("generate", "").strip()
        if text and ("http" not in text and "." in text):
            text = "https://" + text
        if not text or text == url:
            text = url

        try:
            import qrcode
            qr = qrcode.QRCode(box_size=10, border=4)
            qr.add_data(text)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
            img = img.resize((w, h), Image.NEAREST)
        except ImportError:
            img = self._render_qr_fallback(text, w, h)

        draw = ImageDraw.Draw(img)
        self._center_text(draw, text, w // 2, h - 30, self.font_small, fill=(100, 100, 100))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None

    def _render_qr_fallback(self, text, w, h):
        img = Image.new("RGB", (w, h), "white")
        draw = ImageDraw.Draw(img)
        rng = random.Random(abs(hash(text)) & 0x7FFFFFFF)
        size = 30
        offset = (w - size * 10) // 2
        for i in range(size * 2):
            for j in range(size * 2):
                if i < 14 or i >= size * 2 - 14 or j < 14 or j >= size * 2 - 14:
                    v = 1 if ((i + j) % 2 == 0) else 0
                else:
                    v = 1 if rng.random() > 0.5 else 0
                if v:
                    mx, my = offset + j * 10, offset + i * 10
                    draw.rectangle([mx, my, mx + 10, my + 10], fill="black")
        return img

    def _render_binary_tree(self, kw):
        w, h = 900, 650
        img = Image.new("RGB", (w, h), self._colors["bg"])
        draw = ImageDraw.Draw(img)

        values = self._extract_numbers(kw)
        if not values:
            values = [1, 2, 3, 4, 5, 6, 7]
        values.sort()

        if len(values) <= 1:
            root_val = values[0] if values else 1
            nodes = [{"val": root_val, "left": None, "right": None}]
        else:
            nodes = self._build_balanced_bst(values)

        self._draw_tree(draw, nodes[0] if nodes else {"val": 1, "left": None, "right": None},
                        w // 2, 60, w // 4, 90, w, h)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None

    def _build_balanced_bst(self, values):
        if not values:
            return []
        mid = len(values) // 2
        root = {"val": values[mid], "left": None, "right": None}
        left_tree = self._build_balanced_bst(values[:mid])
        right_tree = self._build_balanced_bst(values[mid + 1:])
        if left_tree:
            root["left"] = left_tree[0]
        if right_tree:
            root["right"] = right_tree[0]
        return [root]

    def _draw_tree(self, draw, node, x, y, x_off, y_off, max_w, max_h):
        if node is None:
            return
        r = 24
        if node.get("left"):
            lx = x - x_off
            ly = y + y_off
            draw.line([(x, y + r), (lx, ly - r)], fill=self._colors["line"], width=3)
            self._draw_tree(draw, node["left"], lx, ly,
                            max(x_off // 2, 25), y_off, max_w, max_h)
        if node.get("right"):
            rx = x + x_off
            ry = y + y_off
            draw.line([(x, y + r), (rx, ry - r)], fill=self._colors["line"], width=3)
            self._draw_tree(draw, node["right"], rx, ry,
                            max(x_off // 2, 25), y_off, max_w, max_h)

        self._drop_shadow(draw, x - r, y - r, x + r, y + r, radius=r, offset=3, alpha=25)
        draw.ellipse([x - r, y - r, x + r, y + r],
                     fill=self._colors["primary"], outline=(255, 255, 255, 60), width=3)
        self._center_text(draw, str(node.get("val", "")), x, y, self.font_med, fill="white")

    def _render_flowchart(self, kw):
        w, h = 750, 550
        img = Image.new("RGB", (w, h), self._colors["bg"])
        draw = ImageDraw.Draw(img)

        steps = self._parse_steps(kw)
        if not steps:
            steps = ["Start", "Process", "Decision?", "Output", "End"]

        box_w, box_h = 180, 55
        start_y = 35
        gap_y = 75
        cx = w // 2

        for i, step in enumerate(steps):
            y = start_y + i * (box_h + gap_y)
            is_decision = "?" in step
            color = self._palette[i % len(self._palette)]
            bx1, by1 = cx - box_w // 2, y
            bx2, by2 = cx + box_w // 2, y + box_h

            if is_decision:
                pts = [(cx, y), (cx + box_w // 2, y + box_h // 2),
                       (cx, y + box_h), (cx - box_w // 2, y + box_h // 2)]
                self._drop_shadow(draw, cx - box_w // 2, y, cx + box_w // 2, y + box_h,
                                  radius=0, offset=3, alpha=20)
                draw.polygon(pts, fill=color)
                draw.polygon(pts, outline=(255, 255, 255, 60), width=2)
            else:
                self._drop_shadow(draw, bx1, by1, bx2, by2, radius=10, offset=3, alpha=25)
                self._rounded_box_with_gradient(draw, bx1, by1, bx2, by2, color, radius=10)

            self._center_text(draw, step, cx, y + box_h // 2, self.font_small, fill="white")

            if i < len(steps) - 1:
                ny = start_y + (i + 1) * (box_h + gap_y)
                arrow_y = y + box_h
                draw.line([(cx, arrow_y), (cx, arrow_y + gap_y - 12)], fill=self._colors["line"], width=3)
                draw.polygon([(cx - 6, arrow_y + gap_y - 12), (cx + 6, arrow_y + gap_y - 12),
                              (cx, arrow_y + gap_y)], fill=self._colors["muted"])

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None

    def _render_linked_list(self, kw):
        w, h = 800, 220
        img = Image.new("RGB", (w, h), self._colors["bg"])
        draw = ImageDraw.Draw(img)

        values = self._extract_numbers(kw) or [10, 20, 30, 40, 50]
        box_w, box_h = 80, 55
        arrow_w = 50
        start_x = 40
        y = h // 2 - box_h // 2

        for i, v in enumerate(values):
            x = start_x + i * (box_w + arrow_w)
            self._drop_shadow(draw, x, y, x + box_w, y + box_h, radius=8, offset=3, alpha=25)
            self._rounded_box_with_gradient(draw, x, y, x + box_w, y + box_h,
                                            self._colors["primary"], radius=8)
            self._center_text(draw, str(v), x + box_w // 2, y + box_h // 2, self.font_med, fill="white")

            if i < len(values) - 1:
                ax = x + box_w
                ay = y + box_h // 2
                draw.line([(ax, ay), (ax + arrow_w - 12, ay)], fill=self._colors["line"], width=3)
                draw.polygon([(ax + arrow_w - 12, ay - 6), (ax + arrow_w - 12, ay + 6),
                              (ax + arrow_w, ay)], fill=self._colors["muted"])

        try:
            draw.text((start_x, 10), "Head", fill=self._colors["primary"], font=self.font_small)
            lx = start_x + (len(values) - 1) * (box_w + arrow_w) + box_w + 12
            draw.text((lx, y + box_h // 3), "null", fill=self._colors["muted"], font=self.font_small)
        except Exception:
            pass

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None

    def _render_stack_queue(self, kw):
        w, h = 550, 520
        img = Image.new("RGB", (w, h), self._colors["bg"])
        draw = ImageDraw.Draw(img)

        is_stack = "stack" in kw
        values = self._extract_numbers(kw) or [10, 20, 30, 40, 50]
        box_w, box_h = 140, 48
        start_x = w // 2 - box_w // 2
        start_y = h - 70
        title = "Stack (LIFO)" if is_stack else "Queue (FIFO)"

        self._center_text(draw, title, w // 2, 20, self.font_large, fill=self._colors["text"])

        for i, v in enumerate(values):
            y = start_y - i * (box_h + 6)
            color = self._palette[i % len(self._palette)]
            self._drop_shadow(draw, start_x, y - box_h, start_x + box_w, y, radius=8, offset=3, alpha=25)
            self._rounded_box_with_gradient(draw, start_x, y - box_h, start_x + box_w, y, color, radius=8)
            self._center_text(draw, str(v), start_x + box_w // 2, y - box_h // 2, self.font_med, fill="white")

        try:
            if is_stack:
                ay = start_y - len(values) * (box_h + 6) + 8
                draw.line([(start_x + box_w + 20, ay), (start_x + box_w + 20, start_y - box_h)],
                          fill=self._colors["line"], width=2)
                draw.polygon([(start_x + box_w + 14, ay), (start_x + box_w + 26, ay),
                              (start_x + box_w + 20, ay - 12)], fill=self._colors["muted"])
                draw.text((start_x + box_w + 28, ay + 8), "push", fill=self._colors["muted"], font=self.font_small)
                draw.text((start_x + box_w + 28, start_y - box_h - 18), "pop",
                          fill=self._colors["muted"], font=self.font_small)
        except Exception:
            pass

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None

    def _render_mindmap(self, kw):
        w, h = 750, 550
        img = Image.new("RGB", (w, h), self._colors["bg"])
        draw = ImageDraw.Draw(img)

        topics = self._parse_list(kw) or ["Main Idea", "Subtopic 1", "Subtopic 2", "Subtopic 3", "Detail A", "Detail B"]
        center = (w // 2, h // 2)

        self._drop_shadow(draw, center[0] - 55, center[1] - 55, center[0] + 55, center[1] + 55,
                          radius=55, offset=4, alpha=25)
        draw.ellipse([center[0] - 55, center[1] - 55, center[0] + 55, center[1] + 55],
                     fill=self._colors["primary"])
        draw.ellipse([center[0] - 55, center[1] - 55, center[0] + 55, center[1] + 55],
                     outline=(255, 255, 255, 40), width=2)
        self._center_text(draw, topics[0][:14], center[0], center[1], self.font_small, fill="white")

        for i in range(min(len(topics) - 1, 6)):
            color = self._palette[i % len(self._palette)]
            angle = 2 * math.pi * i / 6 - math.pi / 2
            r = 180
            tx = center[0] + int(r * math.cos(angle))
            ty = center[1] + int(r * math.sin(angle))

            draw.line([center[0], center[1], tx, ty], fill=self._colors["line"], width=3)

            bw, bh = 120, 40
            self._drop_shadow(draw, tx - bw // 2, ty - bh // 2, tx + bw // 2, ty + bh // 2,
                              radius=8, offset=3, alpha=20)
            self._rounded_box_with_gradient(draw, tx - bw // 2, ty - bh // 2,
                                            tx + bw // 2, ty + bh // 2, color, radius=8)
            self._center_text(draw, topics[i + 1][:12], tx, ty, self.font_small, fill="white")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None

    def _render_venn(self, kw):
        w, h = 550, 450
        img = Image.new("RGB", (w, h), self._colors["bg"])
        draw = ImageDraw.Draw(img)

        labels = self._parse_list(kw) or ["Set A", "Set B"]
        c1 = (w // 2 - 75, h // 2)
        c2 = (w // 2 + 75, h // 2)
        r = 120

        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)

        c1c = (108, 92, 231, 130)
        c2c = (72, 149, 239, 130)
        od.ellipse([c1[0] - r, c1[1] - r, c1[0] + r, c1[1] + r], fill=c1c)
        od.ellipse([c2[0] - r, c2[1] - r, c2[0] + r, c2[1] + r], fill=c2c)
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        draw.ellipse([c1[0] - r, c1[1] - r, c1[0] + r, c1[1] + r],
                     outline=(88, 72, 211), width=3)
        draw.ellipse([c2[0] - r, c2[1] - r, c2[0] + r, c2[1] + r],
                     outline=(60, 130, 220), width=3)

        try:
            bbox1 = draw.textbbox((0, 0), labels[0], font=self.font_small)
            tw1 = bbox1[2] - bbox1[0]
            draw.text((c1[0] - tw1 // 2, c1[1] + r + 12), labels[0],
                      fill=self._colors["text"], font=self.font_small)
            if len(labels) > 1:
                bbox2 = draw.textbbox((0, 0), labels[1], font=self.font_small)
                tw2 = bbox2[2] - bbox2[0]
                draw.text((c2[0] - tw2 // 2, c2[1] + r + 12), labels[1],
                          fill=self._colors["text"], font=self.font_small)
        except Exception:
            pass

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None

    def _render_chart(self, kw):
        w, h = 650, 450
        img = Image.new("RGB", (w, h), self._colors["bg"])
        draw = ImageDraw.Draw(img)

        is_pie = "pie" in kw
        values = self._extract_numbers(kw) or [30, 25, 20, 15, 10]
        labels = ["A", "B", "C", "D", "E"]
        colors = self._palette[:len(values)]

        if is_pie:
            total = sum(values)
            start_angle = 0
            cx, cy, pr = w // 2, h // 2, 150
            for i, (v, c) in enumerate(zip(values, colors)):
                angle = 360 * v / total
                draw.pieslice([cx - pr, cy - pr, cx + pr, cy + pr],
                              start_angle, start_angle + angle, fill=c,
                              outline="white", width=3)
                mid_angle = math.radians(start_angle + angle / 2)
                lx = cx + int((pr + 30) * math.cos(mid_angle))
                ly = cy + int((pr + 30) * math.sin(mid_angle))
                self._center_text(draw, f"{labels[i]} ({v})", lx, ly, self.font_small, fill=self._colors["text"])
                start_angle += angle
        else:
            margin = 70
            bar_w = (w - 2 * margin) // len(values)
            max_h = h - 120
            gb = int(bar_w * 0.2)
            for i, (v, c) in enumerate(zip(values, colors)):
                bh = int(max_h * v / max(values))
                bx = margin + i * bar_w + gb
                by = h - 60 - bh
                self._drop_shadow(draw, bx, by, bx + bar_w - 2 * gb, h - 60,
                                  radius=4, offset=3, alpha=20)
                self._rounded_box_with_gradient(draw, bx, by, bx + bar_w - 2 * gb, h - 60, c, radius=4)
                self._center_text(draw, str(v), bx + (bar_w - 2 * gb) // 2, by - 14,
                                  self.font_small, fill=self._colors["text"])
                self._center_text(draw, labels[i], bx + (bar_w - 2 * gb) // 2, h - 40,
                                  self.font_small, fill=self._colors["text"])

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None

    def _render_graph(self, kw):
        w, h = 750, 550
        img = Image.new("RGB", (w, h), self._colors["bg"])
        draw = ImageDraw.Draw(img)

        values = self._extract_numbers(kw)
        node_count = min(len(values), 8) if values else 6
        if node_count < 3:
            node_count = 6
        values = values[:node_count] if values else list(range(1, node_count + 1))

        rng = random.Random(42)
        nodes = []
        for i in range(node_count):
            angle = 2 * math.pi * i / node_count - math.pi / 2
            radius = 190 + rng.randint(-25, 25)
            nx = w // 2 + int(radius * math.cos(angle))
            ny = h // 2 + int(radius * math.sin(angle))
            nodes.append({"x": nx, "y": ny, "val": str(values[i]) if i < len(values) else str(i + 1)})

        edges = []
        for i in range(node_count):
            for j in range(i + 1, node_count):
                if rng.random() > 0.55:
                    edges.append((i, j))

        for i, j in edges:
            draw.line([(nodes[i]["x"], nodes[i]["y"]), (nodes[j]["x"], nodes[j]["y"])],
                      fill=self._colors["line"], width=3)

        for idx, node in enumerate(nodes):
            color = self._palette[idx % len(self._palette)]
            self._drop_shadow(draw, node["x"] - 22, node["y"] - 22, node["x"] + 22, node["y"] + 22,
                              radius=22, offset=3, alpha=25)
            draw.ellipse([node["x"] - 22, node["y"] - 22, node["x"] + 22, node["y"] + 22],
                         fill=color, outline=(255, 255, 255, 40), width=2)
            self._center_text(draw, node["val"], node["x"], node["y"], self.font_small, fill="white")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None

    def _render_architecture(self, kw):
        w, h = 750, 550
        img = Image.new("RGB", (w, h), self._colors["bg"])
        draw = ImageDraw.Draw(img)

        layers = ["Client", "API Gateway", "Microservices", "Database", "Cache"]
        box_w, box_h = 240, 50
        gap = 25
        start_y = 45

        for i, layer in enumerate(layers):
            y = start_y + i * (box_h + gap)
            cx = w // 2
            color = self._palette[i % len(self._palette)]
            bx1, by1 = cx - box_w // 2, y
            bx2, by2 = cx + box_w // 2, y + box_h

            self._drop_shadow(draw, bx1, by1, bx2, by2, radius=10, offset=3, alpha=25)
            self._rounded_box_with_gradient(draw, bx1, by1, bx2, by2, color, radius=10)
            self._center_text(draw, layer, cx, y + box_h // 2, self.font_med, fill="white")

            if i < len(layers) - 1:
                ny = y + box_h
                draw.line([(cx, ny), (cx, ny + gap - 12)], fill=self._colors["line"], width=3)
                draw.polygon([(cx - 6, ny + gap - 12), (cx + 6, ny + gap - 12),
                              (cx, ny + gap)], fill=self._colors["muted"])

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None

    def _render_timeline(self, kw):
        w, h = 750, 300
        img = Image.new("RGB", (w, h), self._colors["bg"])
        draw = ImageDraw.Draw(img)

        events = self._parse_list(kw) or ["Step 1", "Step 2", "Step 3", "Step 4", "Step 5"]
        line_y = h // 2

        # subtle glow under the line
        for g in range(5, 0, -1):
            draw.line([(50, line_y - g), (w - 50, line_y - g)],
                      fill=(100, 100, 120, 10 - g * 2), width=2)

        draw.line([(50, line_y), (w - 50, line_y)], fill=self._colors["line"], width=4)
        spacing = (w - 100) // max(len(events), 2)

        for i, ev in enumerate(events):
            x = 50 + i * spacing + spacing // 2
            color = self._palette[i % len(self._palette)]
            self._drop_shadow(draw, x - 12, line_y - 12, x + 12, line_y + 12,
                              radius=12, offset=2, alpha=25)
            draw.ellipse([x - 12, line_y - 12, x + 12, line_y + 12],
                         fill=color, outline="white", width=3)
            self._center_text(draw, ev[:16], x, line_y + 28, self.font_small, fill=self._colors["text"])

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None

    def _render_uml(self, kw):
        w, h = 650, 450
        img = Image.new("RGB", (w, h), self._colors["bg"])
        draw = ImageDraw.Draw(img)

        class_name = "MyClass"
        attrs = ["- attr1: int", "- attr2: String", "# protected: float"]
        methods = ["+ method1(): void", "+ method2(x: int): bool"]

        cx, cy = w // 2, 50
        bw, bh = 220, 35

        self._drop_shadow(draw, cx - bw // 2, cy, cx + bw // 2, cy + bh + 2,
                          radius=8, offset=4, alpha=30)
        self._rounded_box_with_gradient(draw, cx - bw // 2, cy, cx + bw // 2, cy + bh,
                                        self._colors["primary"], radius=8)
        self._center_text(draw, class_name, cx, cy + bh // 2, self.font_med, fill="white")

        ay = cy + bh
        draw.line([(cx - bw // 2, ay), (cx + bw // 2, ay)], fill="white", width=3)
        attr_h = len(attrs) * 22
        draw.rectangle([cx - bw // 2, ay, cx + bw // 2, ay + attr_h],
                       fill=(235, 236, 250), outline=self._colors["line"], width=1)
        for i, a in enumerate(attrs):
            draw.text((cx - bw // 2 + 10, ay + 6 + i * 22), a,
                      fill=self._colors["text"], font=self.font_small)

        my = ay + attr_h
        draw.line([(cx - bw // 2, my), (cx + bw // 2, my)], fill=self._colors["line"], width=2)
        meth_h = len(methods) * 22
        draw.rectangle([cx - bw // 2, my, cx + bw // 2, my + meth_h],
                       fill=(235, 236, 250), outline=self._colors["line"], width=1)
        for i, m in enumerate(methods):
            draw.text((cx - bw // 2 + 10, my + 6 + i * 22), m,
                      fill=self._colors["text"], font=self.font_small)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None

    def _render_generic_diagram(self, kw):
        w, h = 650, 450
        img = Image.new("RGB", (w, h), self._colors["bg"])
        draw = ImageDraw.Draw(img)

        self._center_text(draw, "Diagram: " + kw[:40], w // 2, h // 2 - 15,
                          self.font_large, fill=self._colors["text"])
        self._center_text(draw, "(Generated by Acronous AI)", w // 2, h // 2 + 25,
                          self.font_small, fill=self._colors["muted"])

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), None

    def _extract_numbers(self, text):
        nums = re.findall(r'\b\d+\b', text)
        return [int(n) for n in nums if 0 < int(n) < 1000]

    def _extract_url(self, text):
        urls = re.findall(r'https?://[^\s]+', text)
        if urls:
            return urls[0]
        domain = re.findall(r'\b([a-zA-Z0-9]+\.(?:com|org|net|io|app|dev|ai))\b', text)
        if domain:
            return "https://" + domain[0]
        return None

    def _parse_steps(self, text):
        lines = [l.strip() for l in text.replace(".", "\n").split("\n") if l.strip()]
        steps = []
        for l in lines:
            l = re.sub(r'^\d+[\.\)]\s*', '', l).strip()
            if l and len(l) > 2 and l not in ("generate", "image", "flowchart", "flow chart"):
                steps.append(l[:25])
        return steps[:8]

    def _parse_list(self, text):
        items = re.findall(r'(?:^|\n)\s*[-*]\s*(.+?)(?:\n|$)', text)
        if items:
            return [i.strip()[:20] for i in items]
        words = [w.strip().capitalize() for w in text.split() if len(w.strip()) > 2]
        return words[:8]
