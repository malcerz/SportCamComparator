import os,sys,time
sys.path.insert(0,'src')
from PySide6.QtWidgets import QApplication,QWidget,QHBoxLayout
from PySide6.QtCore import QTimer,QUrl
from player_widget import PlayerWidget
app=QApplication([]);w=QWidget();layout=QHBoxLayout(w)
players=[PlayerWidget(),PlayerWidget()]
for p,path in zip(players,['D:/GoPro/GX010338.MP4','D:/GoPro/DJI_20261002062647_0003_D.MP4']):
 layout.addWidget(p);p.setSource(QUrl.fromLocalFile(path));p.play()
w.resize(1400,800);w.show()
t=time.perf_counter()
def tick():
 print(round(time.perf_counter()-t,1),[p.position() for p in players],flush=True)
 if time.perf_counter()-t>15:app.quit()
timer=QTimer();timer.timeout.connect(tick);timer.start(1000)
app.exec()
