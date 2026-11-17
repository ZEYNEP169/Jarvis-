import ctypes

SPI_SETCURSORS = 0x0057

# .reg dosyasini merge ettikten sonra bunu calistir; Windows'u oturumu kapatmadan
# kayit defterindeki yeni imlecleri hemen yuklemeye zorlar.
result = ctypes.windll.user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, 0)
print("Yenilendi." if result else "Yenileme basarisiz, oturumu kapatip acmayi dene.")
