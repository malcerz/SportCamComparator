import os
from PIL import Image

ico_path = 'assets/app.ico'
output_dir = 'packaging/windows/msix/Assets'
os.makedirs(output_dir, exist_ok=True)

try:
    img = Image.open(ico_path)
    img = img.convert("RGBA")
    
    # StoreLogo
    img.resize((50, 50), Image.Resampling.LANCZOS).save(os.path.join(output_dir, 'StoreLogo.png'))
    # Square44x44Logo
    img.resize((44, 44), Image.Resampling.LANCZOS).save(os.path.join(output_dir, 'Square44x44Logo.png'))
    # Square150x150Logo
    img.resize((150, 150), Image.Resampling.LANCZOS).save(os.path.join(output_dir, 'Square150x150Logo.png'))
    
    # SplashScreen (620x300)
    # We can center the icon on a transparent or solid background
    splash = Image.new('RGBA', (620, 300), color=(0, 0, 0, 0))
    icon_resized = img.resize((200, 200), Image.Resampling.LANCZOS)
    splash.paste(icon_resized, ((620 - 200) // 2, (300 - 200) // 2), icon_resized)
    splash.save(os.path.join(output_dir, 'SplashScreen.png'))
    
    print("Icons generated from app.ico")
except Exception as e:
    print(f"Error generating icons: {e}")
