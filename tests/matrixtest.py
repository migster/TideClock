# This is a simple test script for multiple 8x8 bi-color LED matrices
# It's based on the Adafruit sample code for the HT16K33 matrix driver and will let you test the 3 boards independently

import board
from adafruit_ht16k33.matrix import Matrix8x8x2

i2c = board.I2C()
matrix = Matrix8x8x2(i2c)

matrix1 = Matrix8x8x2(i2c, address=0x70)
matrix2 = Matrix8x8x2(i2c, address=0x71)
matrix3 = Matrix8x8x2(i2c, address=0x72)

matrix1[0, 0] = matrix.LED_RED
matrix1[4, 4] = matrix.LED_GREEN
matrix1[7, 7] = matrix.LED_YELLOW

matrix2[0, 7] = matrix.LED_YELLOW
matrix2[4, 4] = matrix.LED_GREEN
matrix2[7, 0] = matrix.LED_RED

matrix3[0, 0] = matrix.LED_RED
matrix3[4, 4] = matrix.LED_GREEN
matrix3[7, 7] = matrix.LED_YELLOW