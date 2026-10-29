HOSPITAL BACKGROUND IMAGES
==========================
Put your photos in this folder using these exact file names:

  hospital-bg.jpg          Desktop / tablet background (landscape, about 1920x1080, under ~400 KB)
  hospital-bg-mobile.jpg   Phone background (portrait, about 900x1600, under ~250 KB)  [optional]

If hospital-bg-mobile.jpg is missing, phones use hospital-bg.jpg.
If neither exists, a soft teal medical-cross pattern is shown instead.

Tips
- Choose calm, bright, low-contrast photos (corridor, reception, ward). The app places a
  light wash over the picture so text stays readable on every page.
- To make the picture stronger or fainter, edit --o1 / --o2 (overlay opacity, 0 to 1) in the
  <style> block at the top of static/index.html.
- Use .jpg. To use .webp or .png, change the file name in the same <style> block.
- Rebuild the container after adding images:  docker compose up -d --build
