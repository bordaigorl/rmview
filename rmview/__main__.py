from .rmview import *

if __name__ == '__main__':
  log.setLevel(logging.INFO)
  QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
  ecode = rMViewApp(sys.argv).exec_()
  print('\nBye!')
  sys.exit(ecode)
