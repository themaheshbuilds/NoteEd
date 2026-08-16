import io
from PIL import Image, ImageEnhance, ImageOps

class ImageService:
    @staticmethod
    def enhance_image(image_bytes, auto_rotate=True, target_width=1200):
        """
        Enhances the uploaded image using lightweight Pillow:
        - Auto-rotation based on EXIF
        - Resizes to target_width while maintaining aspect ratio (reducing size/compression)
        - Increases contrast and performs basic sharpening
        - Saves back as compressed JPEG bytes for optimal API consumption
        """
        try:
            img = Image.open(io.BytesIO(image_bytes))
            
            # Auto rotate based on EXIF info
            if auto_rotate:
                img = ImageOps.exif_transpose(img)
                
            # Convert RGBA/Palette to RGB if saving as JPEG
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
                
            # Resize image if it exceeds target width
            width, height = img.size
            if width > target_width:
                aspect_ratio = height / width
                new_height = int(target_width * aspect_ratio)
                img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)
                
            # Increase Contrast
            contrast_enhancer = ImageEnhance.Contrast(img)
            img = contrast_enhancer.enhance(1.3) # 30% increase
            
            # Sharpening
            sharpness_enhancer = ImageEnhance.Sharpness(img)
            img = sharpness_enhancer.enhance(1.5) # 50% increase
            
            # Save to bytes
            output_bytes = io.BytesIO()
            img.save(output_bytes, format="JPEG", quality=85, optimize=True)
            return output_bytes.getvalue()
            
        except Exception as e:
            print(f"Error enhancing image: {e}")
            return image_bytes # Return original if processing fails

