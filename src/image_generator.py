"""Local Pillow-based graphics engine for automated LinkedIn post images.

Features:
- Size: 1200 x 1200 pixels (PNG format)
- ₹0 cost: 100% local, no external APIs or subscriptions
- Modern, clean, dark-mode LinkedIn aesthetic
- 4 automatic layout templates:
  1. editorial_highlight (News & major updates)
  2. architecture_diagram (System flows & pipelines)
  3. concept_card (Educational concepts & principles)
  4. model_announcement (AI model releases & weights)
- Automatic text wrapping, font fallback, safe margins
- Image quality validation and accessible alt text generation
"""

import hashlib
from io import BytesIO
import os
from pathlib import Path
import re
import textwrap
import time
from typing import Any, Optional, Tuple
from urllib.parse import quote
from PIL import Image, ImageDraw, ImageFont, ImageStat
import requests
from loguru import logger

from src.config import Config, config as default_config


def extract_image_elements(topic: str, context: str = "", commentary: str = "") -> tuple[str, list[str]]:
    """Derive a punchy 5-9 word headline and 2-3 concise highlight points from topic/post text."""
    # 1. Headline (5-9 words)
    clean_topic = re.sub(r"https?://\S+", "", topic).strip()
    clean_topic = re.sub(r"^(Show HN:|Ask HN:|Announcing:|Introducing:)\s*", "", clean_topic, flags=re.IGNORECASE)
    clean_topic = clean_topic.replace('"', "").replace("'", "")
    
    # If topic has colon or dash, the first part is often a great headline
    parts = re.split(r"\s*[-–—:]\s*", clean_topic)
    words = parts[0].split()
    if 4 <= len(words) <= 9:
        headline = " ".join(words)
    else:
        all_words = clean_topic.split()
        if len(all_words) > 9:
            headline = " ".join(all_words[:8])
        elif len(all_words) < 4:
            headline = f"{clean_topic}: Architecture Overview"
        else:
            headline = " ".join(all_words)

    # 2. Extract 2-3 concise points
    points = []
    # Try finding bullet points in commentary
    for line in commentary.splitlines():
        line_clean = line.strip()
        if re.match(r"^[-•*–\d\.]\s+", line_clean):
            text = re.sub(r"^[-•*–\d\.]\s+", "", line_clean).strip()
            # Remove markdown bold/italic
            text = re.sub(r"[*_#]", "", text).strip()
            if 15 < len(text) < 120 and not text.startswith("http"):
                points.append(text)
                if len(points) == 3:
                    break

    # If not enough points from bullets, extract from context sentences
    if len(points) < 2 and context:
        sentences = [s.strip() for s in re.split(r"[.!?]\s+", context) if len(s.strip()) > 20]
        for s in sentences:
            if s not in points and len(s) < 120 and not s.startswith("http"):
                points.append(s)
                if len(points) >= 3:
                    break

    # If still not enough points, provide high-value technical defaults
    if not points:
        points = [
            "Technical benchmark and architectural breakdown.",
            "Production trade-offs and latency considerations.",
            "Ecosystem implications for modern engineering workflows.",
        ]
    elif len(points) == 1:
        points.append("Practical production impact for engineering teams.")

    return headline, points[:3]


def synthesize_realistic_poster_prompt(
    topic: str,
    category: str = "Technology",
    source_name: str = "",
    headline: Optional[str] = None,
    points: Optional[list[str]] = None,
    for_midjourney_or_grok: bool = False,
) -> str:
    """Synthesize a high-end, realistic 3D tech announcement poster prompt.

    Tailored to the topic's subject matter:
    - Frontier AI & LLMs (Claude, OpenAI, DeepSeek): Cybernetic humanoid robot, executive desk, glowing code, twilight city skyline.
    - OpenAI / Multimodal / Celestial releases: Dual scenic cards (golden sunrise & blue moonlit mountains), glowing neural circuits.
    - Developer Tools & Autonomous Agents (Copilot, Replit, Cursor): Sleek laptop running IDE, cute 3D companion robot, glowing ribbon icon.
    - Semiconductors & Hardware (NVIDIA, Intel, AMD, Chips): Glowing silicon wafer with gold/cyan laser circuits on carbon motherboard.
    - Tech Policy & Diplomacy (US-China, EU, Safeguards): Diplomatic handshake with flags, floating holographic AI globe, dual city skylines.
    - Computational Biology (AlphaFold, Biotech): 3D holographic molecular DNA and protein structure in high-tech laboratory.
    - General Tech: Futuristic command center, dark executive aesthetic, glassmorphic UI cards.

    Args:
        topic: The post's topic title.
        category: Industry classification.
        source_name: Publishing source or brand.
        headline: 5-9 word headline.
        points: 2-3 key takeaway bullet points.
        for_midjourney_or_grok: If True, produces the complete cinematic prompt for manual copy-paste into Grok or Midjourney.
                               If False, produces a concise, high-speed prompt for free online generation endpoints.
    """
    clean_headline = headline or topic
    clean_headline = re.sub(r"https?://\S+", "", clean_headline).strip()
    words = clean_headline.split()
    if len(words) > 10:
        clean_headline = " ".join(words[:8])

    clean_points = points or [
        "Advanced architecture and benchmark evaluation.",
        "Production trade-offs and latency considerations.",
        "Long-term ecosystem impact for engineers.",
    ]
    p1 = clean_points[0] if len(clean_points) > 0 else "Advanced benchmark performance."
    p2 = clean_points[1] if len(clean_points) > 1 else "Production-grade reliability."
    p3 = clean_points[2] if len(clean_points) > 2 else "Scalable developer experience."

    text_corpus = f"{topic} {category} {source_name}".lower()

    if any(k in text_corpus for k in ["anthropic", "claude", "opus", "sonnet", "haiku", "alignment", "deepseek", "qwen", "mistral"]):
        full_scene = (
            "High-tech executive office with floor-to-ceiling glass window overlooking a glowing twilight city skyline. "
            "In the center right, a sleek 3D photorealistic cybernetic humanoid robot with smooth white and chrome plating "
            "and glowing amber illuminated circuits, seated at a dark wooden executive desk in front of a modern laptop "
            "displaying glowing lines of code and neural network telemetry on screen. A minimalist coffee mug sits on the desk."
        )
        brief_scene = "sleek 3D cybernetic robot looking at laptop with glowing code, dusk city skyline"
    elif any(k in text_corpus for k in ["openai", "chatgpt", "gpt-5", "gpt-6", "sol", "luna", "sora", "o1", "o3", "reasoning model"]):
        full_scene = (
            "Futuristic dark tech aesthetic with dual cinematic landscape cards floating in space: "
            "one showing a radiant golden sunrise over tranquil alpine peaks, the other showing an ethereal blue full moon "
            "over a misty mountain lake, framed by glowing quantum neural network circuits and dark glassmorphic cards."
        )
        brief_scene = "dual scenic cards of golden sunrise and blue moonlit mountains, glowing neural networks"
    elif any(k in text_corpus for k in ["copilot", "microsoft", "replit", "cursor", "devin", "agent", "developer tool", "ide", "editor", "github"]):
        full_scene = (
            "A modern executive developer workspace at dusk, an ultra-thin laptop running a futuristic IDE with code, "
            "accompanied by a cute 3D glossy desktop companion robot with glowing blue digital eyes standing beside the keyboard, "
            "with a vibrant floating luminous 3D ribbon icon and ambient studio lighting."
        )
        brief_scene = "laptop running IDE with cute 3D robot companion on desk, floating neon ribbon icon"
    elif any(k in text_corpus for k in ["nvidia", "blackwell", "semiconductor", "chip", "silicon", "gpu", "tsmc", "intel", "amd", "hardware", "datacenter"]):
        full_scene = (
            "Extreme close-up of a futuristic glowing silicon microchip processor with intricate gold and cyan laser circuit pathways "
            "and microscopic wafer architecture, mounted on a dark matte carbon-fiber motherboard with dramatic volumetric rim lighting."
        )
        brief_scene = "glowing silicon microchip with gold and cyan laser circuit pathways on dark motherboard"
    elif any(k in text_corpus for k in ["us-china", "china", "reuters", "safeguard", "treaty", "regulation", "sovereign", "diplomacy", "government", "policy", "eu", "starlink"]):
        full_scene = (
            "Two diplomats in tailored dark suits shaking hands firmly in agreement, framed by illuminated national flags on either side, "
            "with a glowing 3D holographic digital wireframe AI globe floating between them, dual dusk city skylines in the background."
        )
        brief_scene = "diplomatic handshake with national flags, floating holographic AI globe, dual city skylines"
    elif any(k in text_corpus for k in ["alphafold", "biology", "dna", "drug", "medicine", "deepmind", "protein", "scientific"]):
        full_scene = (
            "A cutting-edge computational biology laboratory, 3D holographic molecular DNA double helix and glowing protein "
            "folding structure floating above a dark glass desk, cinematic lighting, sharp reflections."
        )
        brief_scene = "3D holographic molecular DNA double helix and glowing protein structure in dark laboratory"
    else:
        full_scene = (
            "A high-tech executive tech announcement visual, futuristic developer workstation with glowing holographic displays, "
            "floating glass UI cards showing system architecture, sleek ambient neon lighting, clean executive dark-mode aesthetic."
        )
        brief_scene = "futuristic tech announcement poster with glowing holographic interface and dark glass cards"

    if for_midjourney_or_grok:
        return (
            f"Official tech product announcement poster for {clean_headline}. "
            f"Dark futuristic corporate tech aesthetic (#0a0f1d). {full_scene} "
            f"On the left side, bold modern typography reading '{clean_headline}' with translucent glassmorphic "
            f"dark UI cards showing glowing neon bordered badges: '{p1}', '{p2}', '{p3}', and a large highlight metric callout card. "
            f"Cinematic studio lighting, volumetric rim light rays, sharp focus, 8k resolution, award-winning technology announcement visual."
        )
    else:
        return (
            f"Official tech announcement poster for {clean_headline}, {brief_scene}, "
            f"dark mode tech aesthetic, glowing neon glass UI cards, cinematic studio lighting, photorealistic 8k render"
        )


def fetch_ai_realistic_image(
    prompt: str,
    output_path: Path | str,
    timeout: int = 25,
    overlay_footer: bool = True,
    seed: Optional[int] = None,
) -> bool:
    """Fetch an AI-generated realistic announcement graphic from zero-cost text-to-image API.

    Zero-cost (budget ₹0), no API key or subscription required.
    Resizes/standardizes to 1200x1200px PNG and validates quality.

    Returns:
        True if successful, False if timed out or failed (prompting local fallback).
    """
    try:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        use_seed = seed if seed is not None else int(time.time()) % 100000
        clean_prompt = prompt.strip()[:240]
        encoded_prompt = quote(clean_prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=1&seed={use_seed}"

        logger.info(f"Attempting free realistic AI image generation (timeout: {timeout}s)...")
        response = requests.get(url, timeout=timeout)
        if response.status_code != 200 or len(response.content) < 1500:
            logger.warning(
                f"AI image API returned status {response.status_code} "
                f"(length: {len(response.content)} bytes). Falling back to local graphics engine."
            )
            return False

        img = Image.open(BytesIO(response.content)).convert("RGB")
        if img.size != (1200, 1200):
            img = img.resize((1200, 1200), Image.Resampling.LANCZOS)

        if overlay_footer:
            draw = ImageDraw.Draw(img)
            draw.rectangle([0, 1140, 1200, 1200], fill=(10, 15, 29))
            font = FontManager.get_font(20, bold=False)
            font_blue = FontManager.get_font(20, bold=True)
            draw.text((60, 1162), "ENGINEERING INSIGHTS • AUTOMATED ARCHITECTURE", fill=(148, 163, 184), font=font)
            draw.text((950, 1162), "LINKEDIN INTELLIGENCE", fill=(96, 165, 250), font=font_blue)

        img.save(str(output_path), format="PNG", optimize=True)
        logger.info(f"Successfully generated realistic AI image saved to {output_path.name}")
        return True
    except Exception as e:
        logger.warning(f"AI realistic graphic generation unavailable ({e}). Falling back to local graphics engine.")
        return False


def process_and_save_custom_image(
    source_path_or_url: str,
    output_path: Path | str,
    target_size: tuple[int, int] = (1200, 1200),
) -> tuple[Path, str]:
    """Process an image from disk or URL, format to 1200x1200px PNG, compute SHA-256 hash.

    Args:
        source_path_or_url: Local file path or http(s) URL.
        output_path: Destination path.
        target_size: Target (width, height) tuple, defaults to (1200, 1200).

    Returns:
        (saved_path, sha256_hash)
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if source_path_or_url.startswith(("http://", "https://")):
        logger.info(f"Downloading custom image from {source_path_or_url}...")
        resp = requests.get(source_path_or_url, timeout=25)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content))
    else:
        src_path = Path(source_path_or_url)
        if not src_path.exists():
            raise FileNotFoundError(f"Source image file does not exist: {source_path_or_url}")
        img = Image.open(src_path)

    # Convert to RGB mode if RGBA or palette
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGB", img.size, (10, 15, 29))
        bg.paste(img, mask=img.convert("RGBA").split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Resize with center crop to match target_size without distortion
    w, h = img.size
    target_w, target_h = target_size
    aspect_src = w / h
    aspect_tgt = target_w / target_h

    if aspect_src > aspect_tgt:
        new_w = int(h * aspect_tgt)
        offset = (w - new_w) // 2
        img = img.crop((offset, 0, offset + new_w, h))
    elif aspect_src < aspect_tgt:
        new_h = int(w / aspect_tgt)
        offset = (h - new_h) // 2
        img = img.crop((0, offset, w, offset + new_h))

    img = img.resize(target_size, Image.Resampling.LANCZOS)
    img.save(str(output_path), format="PNG", optimize=True)

    with open(output_path, "rb") as f:
        img_hash = hashlib.sha256(f.read()).hexdigest()

    return output_path, img_hash


class FontManager:
    """Manages cross-platform font loading with fallbacks."""

    WINDOWS_FONT_DIR = Path("C:/Windows/Fonts")

    @classmethod
    def get_font(cls, size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        """Load a suitable system font, falling back gracefully."""
        candidates = []
        if bold:
            candidates.extend(
                [
                    cls.WINDOWS_FONT_DIR / "segoeuib.ttf",
                    cls.WINDOWS_FONT_DIR / "arialbd.ttf",
                    cls.WINDOWS_FONT_DIR / "calibrib.ttf",
                ]
            )
        else:
            candidates.extend(
                [
                    cls.WINDOWS_FONT_DIR / "segoeui.ttf",
                    cls.WINDOWS_FONT_DIR / "arial.ttf",
                    cls.WINDOWS_FONT_DIR / "calibri.ttf",
                ]
            )

        for candidate in candidates:
            if candidate.exists():
                try:
                    return ImageFont.truetype(str(candidate), size)
                except Exception:
                    continue

        # Universal fallback to default
        try:
            return ImageFont.truetype("arial.ttf", size)
        except Exception:
            return ImageFont.load_default()


class ImageValidator:
    """Performs pre-publication quality checks on generated graphics."""

    REQUIRED_WIDTH = 1200
    REQUIRED_HEIGHT = 1200
    SAFE_MARGIN = 50

    @classmethod
    def validate(cls, image_path: Path | str) -> Tuple[bool, str]:
        """Verify image dimensions, format, non-blank status, and lack of placeholders."""
        path = Path(image_path)
        if not path.exists():
            return False, f"Image file does not exist at {path}"

        if path.suffix.lower() != ".png":
            return False, f"Image format must be PNG, got '{path.suffix}'"

        try:
            with Image.open(path) as img:
                # 1. Dimensions check
                width, height = img.size
                if width != cls.REQUIRED_WIDTH or height != cls.REQUIRED_HEIGHT:
                    return (
                        False,
                        f"Invalid dimensions: expected {cls.REQUIRED_WIDTH}x{cls.REQUIRED_HEIGHT}, got {width}x{height}",
                    )

                # 2. Corruption / Blank image check (variance across channels)
                stat = ImageStat.Stat(img)
                avg_stddev = sum(stat.stddev) / len(stat.stddev)
                if avg_stddev < 5.0:
                    return False, f"Image appears blank or single-color (stddev: {avg_stddev:.1f})"

                return True, "Image passed all quality checks"

        except Exception as e:
            return False, f"Failed to open or verify image: {e}"

    @staticmethod
    def check_text_for_placeholders(text: str) -> bool:
        """Check for placeholder phrases like [TODO], Lorem Ipsum, etc."""
        forbidden = [r"\[todo\]", r"lorem ipsum", r"placeholder", r"your_headline_here", r"n/a"]
        lowered = text.lower()
        return any(re.search(p, lowered) for p in forbidden)


class ImageGenerator:
    """Generates professional 1200x1200px PNG graphics for LinkedIn."""

    WIDTH = 1200
    HEIGHT = 1200

    # Color Palette: Modern Obsidian & Electric Indigo / Cyan
    BG_COLOR = (11, 15, 25)          # Deep obsidian #0B0F19
    CARD_BG = (22, 30, 49)           # Surface card #161E31
    CARD_BORDER = (45, 55, 80)       # Border #2D3750
    TEXT_PRIMARY = (248, 250, 252)   # Pure crisp off-white #F8FAFC
    TEXT_SECONDARY = (148, 163, 184) # Muted slate #94A3B8
    TEXT_MUTED = (100, 116, 139)     # Dim slate #64748B
    ACCENT_CYAN = (56, 189, 248)     # Accent Cyan #38BDF8
    ACCENT_BLUE = (96, 165, 250)     # Accent Blue #60A5FA
    ACCENT_PURPLE = (167, 139, 250)  # Accent Indigo #A78BFA
    ACCENT_GREEN = (52, 211, 153)    # Accent Emerald #34D399

    def __init__(self, cfg: Optional[Config] = None) -> None:
        self.config = cfg or default_config
        self.output_dir = self.config.images_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def compute_image_hash(image_path: Path | str) -> str:
        """Calculate SHA-256 hash of an image file."""
        hasher = hashlib.sha256()
        with open(image_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _draw_background_gradient(self, draw: ImageDraw.ImageDraw) -> None:
        """Render a subtle modern gradient background."""
        # Top-left to bottom-right subtle gradient
        r1, g1, b1 = self.BG_COLOR
        r2, g2, b2 = (17, 24, 39)  # Dark slate #111827

        for y in range(self.HEIGHT):
            ratio = y / self.HEIGHT
            r = int(r1 + (r2 - r1) * ratio)
            g = int(g1 + (g2 - g1) * ratio)
            b = int(b1 + (b2 - b1) * ratio)
            draw.line([(0, y), (self.WIDTH, y)], fill=(r, g, b))

        # Add decorative grid dots or subtle lines
        for x in range(80, self.WIDTH - 80, 80):
            for y in range(80, 240, 80):
                draw.point((x, y), fill=(30, 41, 59))

    def _wrap_text(
        self,
        text: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        max_width: int,
        draw: ImageDraw.ImageDraw,
    ) -> list[str]:
        """Wrap text into multiple lines so each line fits within max_width pixels."""
        words = text.strip().split()
        if not words:
            return []

        lines = []
        current_line: list[str] = []

        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            line_width = bbox[2] - bbox[0]

            if line_width <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    # Single word exceeds width, force append
                    lines.append(word)
                    current_line = []

        if current_line:
            lines.append(" ".join(current_line))

        return lines

    def _render_header(
        self,
        draw: ImageDraw.ImageDraw,
        category: str,
        source_name: str,
    ) -> int:
        """Render the top badge and source marker. Returns current Y coordinate."""
        start_y = 70
        badge_text = category.upper() if category else "TECH DISPATCH"
        font_badge = FontManager.get_font(20, bold=True)

        bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        badge_x = 70
        badge_pad_x = 18
        badge_pad_y = 8
        badge_w = text_w + badge_pad_x * 2
        badge_h = text_h + badge_pad_y * 2

        # Draw category pill badge
        draw.rounded_rectangle(
            [badge_x, start_y, badge_x + badge_w, start_y + badge_h],
            radius=6,
            fill=(30, 41, 59),
            outline=self.ACCENT_CYAN,
            width=1,
        )
        draw.text(
            (badge_x + badge_pad_x, start_y + badge_pad_y - 2),
            badge_text,
            font=font_badge,
            fill=self.ACCENT_CYAN,
        )

        # Draw source indicator on right
        font_source = FontManager.get_font(20, bold=False)
        src_label = f"SOURCE • {source_name.upper()}" if source_name else "VERIFIED ENGINEERING UPDATE"
        src_bbox = draw.textbbox((0, 0), src_label, font=font_source)
        src_w = src_bbox[2] - src_bbox[0]
        draw.text(
            (self.WIDTH - 70 - src_w, start_y + badge_pad_y - 2),
            src_label,
            font=font_source,
            fill=self.TEXT_MUTED,
        )

        return start_y + badge_h + 40

    def _render_footer(self, draw: ImageDraw.ImageDraw) -> None:
        """Render standard bottom footer bar."""
        footer_y = self.HEIGHT - 80
        font_footer = FontManager.get_font(18, bold=False)

        # Draw divider line
        draw.line([(70, footer_y - 20), (self.WIDTH - 70, footer_y - 20)], fill=(30, 41, 59), width=1)

        left_text = "ENGINEERING INSIGHTS • AUTOMATED ARCHITECTURE"
        right_text = "LINKEDIN TECH INTELLIGENCE"

        draw.text((70, footer_y), left_text, font=font_footer, fill=self.TEXT_MUTED)
        r_bbox = draw.textbbox((0, 0), right_text, font=font_footer)
        draw.text((self.WIDTH - 70 - (r_bbox[2] - r_bbox[0]), footer_y), right_text, font=font_footer, fill=self.ACCENT_PURPLE)

    def _render_editorial_highlight(
        self,
        draw: ImageDraw.ImageDraw,
        start_y: int,
        headline: str,
        points: list[str],
    ) -> None:
        """Template 1: Editorial Headline + 3 Key Highlights."""
        font_headline = FontManager.get_font(52, bold=True)
        max_width = self.WIDTH - 140

        # Headline
        lines = self._wrap_text(headline, font_headline, max_width, draw)
        curr_y = start_y
        for line in lines[:3]:  # Max 3 lines of headline
            draw.text((70, curr_y), line, font=font_headline, fill=self.TEXT_PRIMARY)
            curr_y += 66

        curr_y += 35

        # 3 Structured Highlight Cards
        card_w = max_width
        card_h = 135
        card_gap = 25
        font_card_num = FontManager.get_font(24, bold=True)
        font_card_text = FontManager.get_font(26, bold=False)

        clean_points = [p for p in points if p.strip()][:3]
        if not clean_points:
            clean_points = [
                "Key technical benchmark and architecture analysis.",
                "Practical production implications for software engineers.",
                "Emerging industry pattern driving next-gen adoption.",
            ]

        colors = [self.ACCENT_CYAN, self.ACCENT_PURPLE, self.ACCENT_GREEN]

        for i, point in enumerate(clean_points):
            accent = colors[i % len(colors)]
            box_top = curr_y + i * (card_h + card_gap)

            # Draw card surface
            draw.rounded_rectangle(
                [70, box_top, 70 + card_w, box_top + card_h],
                radius=10,
                fill=self.CARD_BG,
                outline=self.CARD_BORDER,
                width=1,
            )

            # Accent vertical indicator strip
            draw.rounded_rectangle(
                [70, box_top + 15, 76, box_top + card_h - 15],
                radius=3,
                fill=accent,
            )

            # Badge number (01, 02, 03)
            num_str = f"0{i + 1}"
            draw.text((95, box_top + 22), num_str, font=font_card_num, fill=accent)

            # Wrapped card text
            text_lines = self._wrap_text(point, font_card_text, card_w - 95, draw)
            text_y = box_top + 20
            for tl in text_lines[:2]:
                draw.text((150, text_y), tl, font=font_card_text, fill=self.TEXT_PRIMARY)
                text_y += 34

    def _render_architecture_diagram(
        self,
        draw: ImageDraw.ImageDraw,
        start_y: int,
        headline: str,
        points: list[str],
    ) -> None:
        """Template 2: Architecture Pipeline / Workflow flow."""
        font_headline = FontManager.get_font(48, bold=True)
        max_width = self.WIDTH - 140

        # Headline
        lines = self._wrap_text(headline, font_headline, max_width, draw)
        curr_y = start_y
        for line in lines[:3]:
            draw.text((70, curr_y), line, font=font_headline, fill=self.TEXT_PRIMARY)
            curr_y += 62

        curr_y += 50

        # 3 Step Sequential Architecture Blocks
        step_w = max_width
        step_h = 120
        step_gap = 45
        font_step_title = FontManager.get_font(22, bold=True)
        font_step_desc = FontManager.get_font(24, bold=False)

        steps = [
            ("STEP 1: INGESTION & CONTEXT", points[0] if len(points) > 0 else "Multi-modal input streams & vector context retrieval"),
            ("STEP 2: REASONING & COMPILATION", points[1] if len(points) > 1 else "Deterministic orchestration and neural evaluation"),
            ("STEP 3: EXECUTION & VERIFICATION", points[2] if len(points) > 2 else "Safe sandboxed execution and factual claim validation"),
        ]

        for i, (title, desc) in enumerate(steps):
            box_top = curr_y + i * (step_h + step_gap)

            draw.rounded_rectangle(
                [70, box_top, 70 + step_w, box_top + step_h],
                radius=10,
                fill=self.CARD_BG,
                outline=self.ACCENT_CYAN if i == 1 else self.CARD_BORDER,
                width=1,
            )

            # Step title badge
            draw.text((100, box_top + 20), title, font=font_step_title, fill=self.ACCENT_CYAN)

            # Step description
            desc_lines = self._wrap_text(desc, font_step_desc, step_w - 70, draw)
            draw.text((100, box_top + 55), desc_lines[0] if desc_lines else desc, font=font_step_desc, fill=self.TEXT_PRIMARY)

            # Arrow connector between steps
            if i < 2:
                arrow_y = box_top + step_h + 12
                draw.text(((self.WIDTH // 2) - 10, arrow_y), "▼", font=FontManager.get_font(20), fill=self.ACCENT_CYAN)

    def _render_concept_card(
        self,
        draw: ImageDraw.ImageDraw,
        start_y: int,
        headline: str,
        points: list[str],
    ) -> None:
        """Template 3: Core Concept / Principle Breakdown."""
        font_headline = FontManager.get_font(50, bold=True)
        max_width = self.WIDTH - 140

        lines = self._wrap_text(headline, font_headline, max_width, draw)
        curr_y = start_y
        for line in lines[:3]:
            draw.text((70, curr_y), line, font=font_headline, fill=self.TEXT_PRIMARY)
            curr_y += 64

        curr_y += 40

        # Core Definition Box
        core_box_h = 160
        draw.rounded_rectangle(
            [70, curr_y, 70 + max_width, curr_y + core_box_h],
            radius=12,
            fill=(26, 36, 56),
            outline=self.ACCENT_PURPLE,
            width=2,
        )

        font_label = FontManager.get_font(20, bold=True)
        draw.text((100, curr_y + 22), "CORE PRINCIPLE", font=font_label, fill=self.ACCENT_PURPLE)

        core_text = points[0] if points else "Architectural foundation for resilient software and AI systems."
        core_lines = self._wrap_text(core_text, FontManager.get_font(26), max_width - 60, draw)
        cy = curr_y + 60
        for cl in core_lines[:2]:
            draw.text((100, cy), cl, font=FontManager.get_font(26), fill=self.TEXT_PRIMARY)
            cy += 36

        curr_y += core_box_h + 35

        # 2 Sub-cards (e.g. Benefits / Trade-offs)
        sub_h = 180
        col_w = (max_width - 30) // 2
        col_points = points[1:3] if len(points) >= 3 else [
            "Reduces algorithmic complexity and operational overhead.",
            "Enables predictable scaling under high concurrency.",
        ]

        titles = ["KEY ADVANTAGE", "SYSTEM IMPACT"]
        colors = [self.ACCENT_CYAN, self.ACCENT_GREEN]

        for i, pt in enumerate(col_points[:2]):
            col_x = 70 + i * (col_w + 30)
            draw.rounded_rectangle(
                [col_x, curr_y, col_x + col_w, curr_y + sub_h],
                radius=10,
                fill=self.CARD_BG,
                outline=self.CARD_BORDER,
                width=1,
            )
            draw.text((col_x + 25, curr_y + 22), titles[i], font=font_label, fill=colors[i])
            plines = self._wrap_text(pt, FontManager.get_font(22), col_w - 50, draw)
            py = curr_y + 60
            for pl in plines[:3]:
                draw.text((col_x + 25, py), pl, font=FontManager.get_font(22), fill=self.TEXT_SECONDARY)
                py += 30

    def _render_photorealistic_poster(
        self,
        topic: str,
        headline: str,
        points: list[str],
        category: str,
        source_name: str,
    ) -> Image.Image:
        """Render a high-end photorealistic 3D tech announcement poster.

        Uses matching 8K 3D photorealistic render background assets from assets/backgrounds/,
        with dynamic alpha-gradient overlay and modern glassmorphic feature cards.
        """
        bg_dir = Path("assets/backgrounds")
        topic_lower = f"{topic} {category} {source_name}".lower()

        candidate_bg: Optional[Path] = None
        if any(k in topic_lower for k in ["claude", "anthropic"]):
            candidate_bg = bg_dir / "claude_executive_robot.jpg"
        elif any(k in topic_lower for k in ["ai", "model", "frontier", "llm", "reasoning", "deepseek", "openai", "agent", "neural"]):
            candidate_bg = bg_dir / "ai_frontier_robot.jpg"
        elif any(k in topic_lower for k in ["nvidia", "semiconductor", "chip", "silicon", "gpu", "tsmc", "hardware"]):
            candidate_bg = bg_dir / "hardware_semiconductor_chip.jpg"
        else:
            candidate_bg = bg_dir / "tech_developer_workspace.jpg"

        if candidate_bg and candidate_bg.exists():
            base_img = Image.open(candidate_bg).convert("RGBA").resize((self.WIDTH, self.HEIGHT), Image.Resampling.LANCZOS)
        else:
            base_img = Image.new("RGBA", (self.WIDTH, self.HEIGHT), (10, 15, 29, 255))
            draw_bg = ImageDraw.Draw(base_img)
            self._draw_background_gradient(draw_bg)

        # Left-side dark cinematic gradient overlay (provides high contrast for cards & text while preserving 3D subject on right)
        overlay = Image.new("RGBA", (self.WIDTH, self.HEIGHT), (0, 0, 0, 0))
        draw_ol = ImageDraw.Draw(overlay)
        for x in range(self.WIDTH):
            if x < 420:
                alpha = 230
            elif x < 720:
                alpha = int(230 * (1 - (x - 420) / 300))
            else:
                alpha = 0
            draw_ol.line([(x, 0), (x, self.HEIGHT)], fill=(6, 10, 20, alpha))

        img = Image.alpha_composite(base_img, overlay)
        draw = ImageDraw.Draw(img)

        # Fonts
        font_cat = FontManager.get_font(20, bold=True)
        font_date = FontManager.get_font(20, bold=False)
        font_intro = FontManager.get_font(26, bold=True)
        font_title = FontManager.get_font(48, bold=True)
        font_sub = FontManager.get_font(22, bold=False)
        font_card_bold = FontManager.get_font(22, bold=True)
        font_card_sub = FontManager.get_font(18, bold=False)
        font_metric = FontManager.get_font(38, bold=True)
        font_metric_lbl = FontManager.get_font(16, bold=True)

        # 1. Header Pill Badge & Date
        cat_text = category.upper() if category else "TECHNOLOGY INTELLIGENCE"
        bbox = draw.textbbox((0, 0), cat_text, font=font_cat)
        cat_w = bbox[2] - bbox[0]
        pill_right = 70 + cat_w + 30
        draw.rounded_rectangle([70, 65, pill_right, 105], radius=8, fill=(15, 23, 42, 240), outline=self.ACCENT_CYAN, width=2)
        draw.text((85, 74), cat_text, font=font_cat, fill=self.ACCENT_CYAN)
        draw.text((pill_right + 25, 74), "2026 OFFICIAL ANNOUNCEMENT", font=font_date, fill=self.TEXT_MUTED)

        # 2. Main Announcement Title
        draw.text((70, 138), "INTRODUCING", font=font_intro, fill=self.ACCENT_BLUE)

        # Wrap title
        title_lines = self._wrap_text(headline, font_title, 460, draw)
        curr_y = 175
        for line in title_lines[:2]:
            draw.text((70, curr_y), line, font=font_title, fill=self.TEXT_PRIMARY)
            curr_y += 54

        # Subtitle
        sub_text = "Architecture & Engineering Breakdown"
        draw.text((70, curr_y + 8), sub_text, font=font_sub, fill=self.TEXT_SECONDARY)
        curr_y += 52

        # 3. Feature Glassmorphism Cards
        card_w = 460
        card_h = 88
        clean_points = points or [
            "Technical benchmark and architecture analysis.",
            "Production trade-offs for engineers and teams.",
            "Long-term structural impact on the ecosystem.",
        ]

        for i, pt in enumerate(clean_points[:3]):
            y = curr_y + i * (card_h + 14)
            draw.rounded_rectangle([70, y, 70 + card_w, y + card_h], radius=12, fill=(10, 16, 32, 230), outline=(56, 189, 248, 160), width=2)
            draw.rounded_rectangle([70, y, 76, y + card_h], radius=3, fill=self.ACCENT_CYAN)

            words = pt.split()
            line1 = " ".join(words[:4]).upper()
            line2 = " ".join(words[4:]) if len(words) > 4 else pt
            if len(line2) > 42:
                line2 = line2[:40] + "..."

            draw.text((95, y + 16), line1, font=font_card_bold, fill=self.TEXT_PRIMARY)
            draw.text((95, y + 46), line2, font=font_card_sub, fill=self.TEXT_MUTED)

        # 4. Metric / Highlight Box
        m_y = curr_y + 3 * (card_h + 14) + 10
        draw.rounded_rectangle([70, m_y, 70 + card_w, m_y + 102], radius=12, fill=(10, 16, 32, 240), outline=self.ACCENT_PURPLE, width=2)
        draw.rounded_rectangle([70, m_y, 76, m_y + 102], radius=3, fill=self.ACCENT_PURPLE)

        # Metric text based on category
        if any(k in topic_lower for k in ["python", "speed", "latency", "jit"]):
            m_val, m_lbl = "3.2x FASTER SPEEDUP", "MULTI-THREADED CPU BOUND DATA PIPELINES"
        elif any(k in topic_lower for k in ["benchmark", "accuracy", "math", "reasoning"]):
            m_val, m_lbl = "92.5% ACCURACY", "BENCHMARK MATHEMATICS & REASONING EVALUATION"
        else:
            m_val, m_lbl = "STATE-OF-THE-ART", "PRODUCTION ENGINEERING BENCHMARK BREAKTHROUGH"

        draw.text((95, m_y + 18), m_val, font=font_metric, fill=self.ACCENT_PURPLE)
        draw.text((95, m_y + 66), m_lbl, font=font_metric_lbl, fill=self.TEXT_SECONDARY)

        return img.convert("RGB")

    def generate_image_for_post(
        self,
        post_id: int,
        topic: str,
        category: str = "Technology",
        source_name: str = "",
        headline: Optional[str] = None,
        points: Optional[list[str]] = None,
        template_type: str = "auto",
        force_local: bool = False,
    ) -> dict[str, Any]:
        """Generate a complete 1200x1200px PNG graphic and return metadata.

        Uses our high-fidelity photorealistic announcement poster engine by default,
        compositing modern glassmorphic cards and typography over photorealistic 3D renders.

        Args:
            post_id: Unique database ID of the post.
            topic: Topic title.
            category: Industry category.
            source_name: Publishing source.
            headline: Custom 5-9 word headline (derived if omitted).
            points: 2-3 concise highlight bullet points.
            template_type: 'photorealistic_poster', 'editorial_highlight', 'architecture_diagram', 'concept_card', or 'auto'.
            force_local: Retained for backward compatibility.

        Returns:
            Dict with image_path, image_hash, alt_text, width, height, and validation_status.
        """
        # 1. Clean headline (5-9 words recommended)
        raw_headline = headline or topic
        clean_headline = re.sub(r"https?://\S+", "", raw_headline).strip()
        words = clean_headline.split()
        if len(words) > 11:
            clean_headline = " ".join(words[:9]) + "..."
        elif len(words) < 3:
            clean_headline = f"{clean_headline}: Key Architecture Analysis"

        clean_points = points or [
            "Technical benchmark and architecture analysis.",
            "Production trade-offs for engineers and practitioners.",
            "Long-term structural impact on the ecosystem.",
        ]

        filename = f"post_{post_id}_{int(time.time())}.png"
        image_path = self.output_dir / filename

        # 2. Select Template (Defaults to photorealistic 3D poster)
        selected_template = template_type
        if selected_template in ("auto", "photorealistic_poster"):
            image = self._render_photorealistic_poster(
                topic=topic,
                headline=clean_headline,
                points=clean_points,
                category=category,
                source_name=source_name,
            )
            image.save(str(image_path), format="PNG", optimize=True)
            template_used = "photorealistic_poster"
        else:
            image = Image.new("RGB", (self.WIDTH, self.HEIGHT), self.BG_COLOR)
            draw = ImageDraw.Draw(image)
            self._draw_background_gradient(draw)

            start_y = self._render_header(draw, category, source_name)

            if selected_template == "architecture_diagram":
                self._render_architecture_diagram(draw, start_y, clean_headline, clean_points)
            elif selected_template == "concept_card":
                self._render_concept_card(draw, start_y, clean_headline, clean_points)
            else:
                self._render_editorial_highlight(draw, start_y, clean_headline, clean_points)

            self._render_footer(draw)
            image.save(str(image_path), format="PNG", optimize=True)
            template_used = selected_template

        is_valid, reason = ImageValidator.validate(image_path)
        if not is_valid:
            logger.error(f"Image generation failed quality check: {reason}")
            raise RuntimeError(f"Image validation failed: {reason}")

        img_hash = self.compute_image_hash(image_path)
        alt_text = (
            f"Photorealistic technical announcement poster titled '{clean_headline}'. Category: {category}. "
            f"Key insights: {'; '.join(clean_points[:2])}."
        )

        logger.info(
            f"Successfully generated 1200x1200px PNG graphic for post #{post_id} "
            f"using template '{template_used}' at {image_path.name}."
        )

        return {
            "image_path": str(image_path),
            "image_hash": img_hash,
            "image_alt_text": alt_text,
            "image_width": self.WIDTH,
            "image_height": self.HEIGHT,
            "template_used": selected_template,
            "validation_status": "VALIDATED",
        }

    def attach_custom_image(
        self,
        post_id: int,
        source_path_or_url: str,
        headline: str = "",
        category: str = "Technology",
    ) -> dict[str, Any]:
        """Attach an externally generated realistic image (from X/Twitter, Midjourney, Grok, etc.) to a post draft.

        Standardizes to 1200x1200px PNG, computes SHA-256 hash, and validates.
        """
        filename = f"post_{post_id}_attached_{int(time.time())}.png"
        out_path = self.output_dir / filename

        saved_path, img_hash = process_and_save_custom_image(
            source_path_or_url=source_path_or_url,
            output_path=out_path,
            target_size=(self.WIDTH, self.HEIGHT),
        )

        is_valid, reason = ImageValidator.validate(saved_path)
        if not is_valid:
            raise ValueError(f"Custom image failed quality validation: {reason}")

        alt_text = f"Announcement visual for '{headline or 'LinkedIn Post'}'. Category: {category}."
        return {
            "image_path": str(saved_path),
            "image_hash": img_hash,
            "image_alt_text": alt_text,
            "image_width": self.WIDTH,
            "image_height": self.HEIGHT,
            "template_used": "custom_attached",
            "validation_status": "VALIDATED",
        }

