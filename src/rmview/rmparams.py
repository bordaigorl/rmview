WIDTH = 1404
HEIGHT = 1872
PIXELS_NUM = WIDTH * HEIGHT
TOTAL_BYTES = PIXELS_NUM * 2

# evtype_sync = 0
e_type_key = 1
e_type_abs = 3

# evcode_stylus_distance = 25
# evcode_stylus_xtilt = 26
# evcode_stylus_ytilt = 27
e_code_stylus_xpos = 1
e_code_stylus_ypos = 0
e_code_stylus_pressure = 24
# evcode_finger_xpos = 53
# evcode_finger_ypos = 54
# evcode_finger_pressure = 58
e_code_stylus_proximity = 320

stylus_width = 15725
stylus_height = 20951


# Heuristic detection of orientation
# based on locating the menu button (O) and close button (X)

CIRCLE_BLACK = [
  (-18,0), (-13,-13), (0,-18), (13,-13), (18,0), (13,13), (0,18), (-13,13)
]
CIRCLE_WHITE = [
  (-14,0), (-10,-10), (0,-14), (10,-10), (14,0), (10,10), (0,14), (-10,10)
]
CIRCLE_ICON = [(-5,-5), (-5,5), (5,-5), (5,5)]

CIRCLE_POS = [(59,60), (60,1812), (1343,60)]

BLACK = 4278190080
WHITE = 4294967295

O_BUTTON = 1
X_BUTTON = 2

def find_circle_buttons(img):
  return [find_circle_button(img, x, y) for (x,y) in CIRCLE_POS]

def find_circle_button(img, x, y):
  p = img.pixel
  for (dx,dy) in CIRCLE_BLACK:
    if p(x+dx,y+dy) != BLACK:
      return None
  for (dx,dy) in CIRCLE_WHITE:
    if p(x+dx,y+dy) != WHITE:
      return None
  b = [p(x+dx,y+dy) == BLACK for (dx,dy) in CIRCLE_ICON]
  if all(b):
    return X_BUTTON
  if sum(b) == 1:
    return O_BUTTON
  else:
    return None


# NAMES = {
#   BLACK: 'b',
#   WHITE: 'w'
# }

# def debug_circle_buttons(img):
#   return [debug_circle_button(img, x, y) for (x,y) in CIRCLE_POS]

# def debug_circle_button(img, x, y):
#   p = img.pixel
#   b = [ NAMES.get(p(x+dx,y+dy), 'x') for (dx,dy) in CIRCLE_BLACK ]
#   w = [ NAMES.get(p(x+dx,y+dy), 'x') for (dx,dy) in CIRCLE_WHITE ]
#   i = [ NAMES.get(p(x+dx,y+dy), 'x') for (dx,dy) in CIRCLE_ICON ]
#   return (b,w,i)
