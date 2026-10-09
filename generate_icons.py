import os
from PIL import Image

output_dir = 'packaging/windows/msix/Assets'
os.makedirs(output_dir, exist_ok=True)

# Generate simple placeholders using a blue square
def make_icon(name, width, height):
    img = Image.new('RGBA', (width, height), color=(0, 120, 215, 255))
    img.save(os.path.join(output_dir, name))

make_icon('StoreLogo.png', 50, 50)
make_icon('Square44x44Logo.png', 44, 44)
make_icon('Square150x150Logo.png', 150, 150)
make_icon('SplashScreen.png', 620, 300)

print("Icons generated.")
