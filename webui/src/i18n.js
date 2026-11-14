import { useEffect, useState } from "react";

export const LANGUAGES = [
  ["en", "English"], ["es", "Español"], ["ca", "Català"], ["gl", "Galego"],
  ["eu", "Euskara"], ["pt", "Português"], ["fr", "Français"], ["de", "Deutsch"],
  ["it", "Italiano"], ["zh", "中文"], ["ja", "日本語"], ["ru", "Русский"],
  ["ar", "العربية"], ["tr", "Türkçe"]
];

const EN = {
  refresh:"Refresh", language:"Interface language", keyboard:"Keyboard layout",
  tagline:"Rescue, disk imaging and network deployment appliance",
  failed:"Operation failed", host:"Host", images:"Images", jobs:"Deployment jobs",
  manifests:"Manifest-backed local images", recordedJobs:"Recorded jobs and recovery state",
  loading:"Loading Feclora", imaging:"Imaging operations", inventory:"Storage inventory",
  system:"System", wizard:"Operation wizard", chooseOperation:"Choose an operation, review the selected devices, and explicitly confirm every destructive target.",
  operation:"Operation", start:"Start operation", working:"Working…", completed:"Operation completed",
  safety:"Safety model", storageSafety:"Feclora rechecks block-device identity, mounted/system-source safety, geometry and image integrity in the storage engine immediately before writing. A browser selection is not treated as authorization by itself.",
  systemStatus:"System status", component:"Component", status:"Status", configured:"Configured",
  notConfigured:"Not configured", security:"Local image security", generateSecurity:"Generate a local Feclora CA and optional age identity. Private keys remain on this machine; captured images can then be encrypted when selected.",
  capability:"Capability", ready:"Ready", notInitialized:"Not initialized", initializeKeys:"Initialize local security keys",
  terminal:"Terminal access", terminalHelp:"For system setup, network diagnostics and advanced administration, use Cockpit's Terminal page. Do not use the terminal to bypass Feclora's storage safety checks.",
  footer:"All storage operations use Feclora's shared Python engines. Cockpit is the primary operator interface.",
  chooseLayout:"Choose the physical keyboard mapping independently of the interface language. This setting updates the persistent Linux virtual-console keymap and the active text console.",
  applyLayout:"Apply keyboard layout", layoutApplied:"Keyboard layout applied", layoutFailed:"Keyboard layout could not be applied",
  currentKeymap:"Current Linux keymap", scope:"Scope", consoleOnly:"The current implementation configures the Linux virtual console. The Cage/Wayland graphical session still needs a separate XKB runtime integration; this control does not claim to change that session yet.",
  operationLabels:"Operation labels", source:"Source", destination:"Destination", confirm:"Typed confirmation",
  storageDevices:"Block devices and partitions", device:"Device", type:"Type", size:"Size", model:"Model", filesystem:"Filesystem", mounts:"Mountpoints", keyboardScope:"Scope", keyboardScopeText:"The selected layout is persisted for the Linux virtual console and Cage/Wayland XKB environment. The kiosk session restarts shortly so the graphical session can load the new layout.", keyboardAppliedNotice:"The keyboard layout was applied. The kiosk session will restart shortly.",
  exportP2v:"Export P2V QCOW2 from S3"
};
const DICTS = {
es:{
refresh:"Actualizar",language:"Idioma de la interfaz",keyboard:"Distribución del teclado",tagline:"Sistema de rescate, imágenes de disco y despliegue en red",failed:"Operación fallida",host:"Equipo",images:"Imágenes",jobs:"Tareas de despliegue",manifests:"Imágenes locales con manifiesto",recordedJobs:"Tareas registradas y estado de recuperación",loading:"Cargando Feclora",imaging:"Operaciones de imagen",inventory:"Inventario de almacenamiento",system:"Sistema",wizard:"Asistente de operaciones",chooseOperation:"Elige una operación, revisa los dispositivos y confirma expresamente cada destino destructivo.",operation:"Operación",start:"Iniciar operación",working:"En curso…",completed:"Operación completada",safety:"Modelo de seguridad",systemStatus:"Estado del sistema",component:"Componente",status:"Estado",configured:"Configurado",notConfigured:"No configurado",security:"Seguridad local de imágenes",generateSecurity:"Genera una CA local de Feclora y una identidad age opcional. Las claves privadas permanecen en este equipo.",capability:"Capacidad",ready:"Preparado",notInitialized:"No inicializado",initializeKeys:"Inicializar claves de seguridad locales",terminal:"Acceso al terminal",applyLayout:"Aplicar distribución del teclado",layoutApplied:"Distribución aplicada",layoutFailed:"No se pudo aplicar la distribución",currentKeymap:"Mapa de teclado Linux actual",scope:"Ámbito",source:"Origen",destination:"Destino",confirm:"Confirmación escrita",storageDevices:"Discos y particiones",device:"Dispositivo",type:"Tipo",size:"Tamaño",model:"Modelo",filesystem:"Sistema de archivos",mounts:"Puntos de montaje",keyboardScope:"Ámbito",keyboardScopeText:"La distribución seleccionada se guarda para la consola virtual de Linux y el entorno XKB de Cage/Wayland. La sesión del quiosco se reiniciará en breve para cargar la nueva distribución.",keyboardAppliedNotice:"Se ha aplicado la distribución del teclado. La sesión del quiosco se reiniciará en breve."
,exportP2v:"Exportar QCOW2 P2V desde S3"},
ca:{
refresh:"Actualitza",language:"Idioma de la interfície",keyboard:"Distribució del teclat",tagline:"Sistema de rescat, imatges de disc i desplegament en xarxa",failed:"L'operació ha fallat",host:"Equip",images:"Imatges",jobs:"Tasques de desplegament",manifests:"Imatges locals amb manifest",recordedJobs:"Tasques enregistrades i estat de recuperació",loading:"S'està carregant Feclora",imaging:"Operacions d'imatge",inventory:"Inventari d'emmagatzematge",system:"Sistema",wizard:"Assistent d'operacions",chooseOperation:"Tria una operació, revisa els dispositius seleccionats i confirma explícitament cada destinació destructiva.",operation:"Operació",start:"Inicia l'operació",working:"En curs…",completed:"Operació completada",safety:"Model de seguretat",storageSafety:"Feclora torna a comprovar la identitat dels dispositius, els muntatges, la geometria i la integritat de la imatge just abans d'escriure. La selecció al navegador no és una autorització.",systemStatus:"Estat del sistema",component:"Component",status:"Estat",configured:"Configurat",notConfigured:"No configurat",security:"Seguretat local de les imatges",generateSecurity:"Genera una CA local de Feclora i una identitat age opcional. Les claus privades romanen en aquest equip.",capability:"Capacitat",ready:"Preparat",notInitialized:"No inicialitzat",initializeKeys:"Inicialitza les claus de seguretat locals",terminal:"Accés al terminal",terminalHelp:"Per a la configuració del sistema, el diagnòstic de xarxa i l'administració avançada, utilitza la pàgina Terminal de Cockpit. No la facis servir per esquivar les comprovacions de seguretat de Feclora.",footer:"Totes les operacions d'emmagatzematge utilitzen els motors Python compartits de Feclora. Cockpit és la interfície principal.",chooseLayout:"Tria la distribució física del teclat independentment de l'idioma de la interfície. Aquesta opció actualitza el mapa persistent de la consola virtual Linux i la consola de text activa.",applyLayout:"Aplica la distribució del teclat",layoutApplied:"Distribució del teclat aplicada",layoutFailed:"No s'ha pogut aplicar la distribució del teclat",currentKeymap:"Mapa de teclat Linux actual",scope:"Abast",consoleOnly:"Aquesta implementació configura la consola virtual Linux. La sessió gràfica Cage/Wayland encara necessita una integració XKB pròpia; aquest control encara no modifica aquella sessió.",source:"Origen",destination:"Destinació",confirm:"Confirmació escrita",storageDevices:"Dispositius de bloc i particions",device:"Dispositiu",type:"Tipus",size:"Mida",model:"Model",filesystem:"Sistema de fitxers",mounts:"Punts de muntatge",keyboardScope:"Abast",keyboardScopeText:"La distribució seleccionada es desa per a la consola virtual de Linux i l'entorn XKB de Cage/Wayland. La sessió del quiosc es reiniciarà aviat perquè la sessió gràfica carregui la nova distribució.",keyboardAppliedNotice:"S'ha aplicat la distribució del teclat. La sessió del quiosc es reiniciarà aviat."
,exportP2v:"Exporta el QCOW2 P2V des de S3"},
gl:{refresh:"Actualizar",language:"Idioma da interface",keyboard:"Disposición do teclado",tagline:"Sistema de rescate, imaxes de disco e despregamento en rede",failed:"Fallou a operación",host:"Equipo",images:"Imaxes",jobs:"Tarefas de despregamento",imaging:"Operacións de imaxe",inventory:"Inventario de almacenamento",system:"Sistema",wizard:"Asistente de operacións",operation:"Operación",start:"Iniciar operación",working:"En curso…",completed:"Operación completada",systemStatus:"Estado do sistema",component:"Compoñente",status:"Estado",configured:"Configurado",notConfigured:"Non configurado",security:"Seguridade local das imaxes",initializeKeys:"Inicializar claves de seguridade locais",terminal:"Acceso ao terminal",applyLayout:"Aplicar disposición do teclado",layoutApplied:"Disposición aplicada",layoutFailed:"Non se puido aplicar a disposición",source:"Orixe",destination:"Destino",confirm:"Confirmación escrita",device:"Dispositivo",type:"Tipo",size:"Tamaño",keyboardScope:"Ámbito",keyboardScopeText:"A disposición seleccionada gárdase para a consola virtual de Linux e o contorno XKB de Cage/Wayland. A sesión do quiosco reiniciarase axiña para cargar a nova disposición.",keyboardAppliedNotice:"Aplicouse a disposición do teclado. A sesión do quiosco reiniciarase axiña.",exportP2v:"Exportar QCOW2 P2V desde S3"},
eu:{refresh:"Freskatu",language:"Interfazearen hizkuntza",keyboard:"Teklatuaren diseinua",tagline:"Erreskate-, disko-irudi eta sareko hedapen-sistema",failed:"Eragiketak huts egin du",host:"Ostalaria",images:"Irudiak",jobs:"Hedapen-lanak",imaging:"Irudi-eragiketak",inventory:"Biltegiratze-inbentarioa",system:"Sistema",wizard:"Eragiketen morroia",operation:"Eragiketa",start:"Hasi eragiketa",working:"Lanean…",completed:"Eragiketa amaituta",systemStatus:"Sistemaren egoera",component:"Osagaia",status:"Egoera",configured:"Konfiguratuta",notConfigured:"Konfiguratu gabe",security:"Irudien segurtasun lokala",initializeKeys:"Hasieratu segurtasun-gako lokalak",terminal:"Terminalerako sarbidea",applyLayout:"Aplikatu teklatuaren diseinua",layoutApplied:"Teklatuaren diseinua aplikatuta",layoutFailed:"Ezin izan da diseinua aplikatu",source:"Iturburua",destination:"Helburua",confirm:"Idatzizko berrespena",device:"Gailua",type:"Mota",size:"Tamaina",keyboardScope:"Esparrua",keyboardScopeText:"Hautatutako diseinua Linux kontsola birtualerako eta Cage/Wayland XKB ingurunerako gordetzen da. Kiosko-saioa laster berrabiaraziko da diseinu berria saio grafikoan kargatzeko.",keyboardAppliedNotice:"Teklatuaren diseinua aplikatu da. Kiosko-saioa laster berrabiaraziko da.",exportP2v:"Esportatu P2V QCOW2 S3tik"},
pt:{refresh:"Atualizar",language:"Idioma da interface",keyboard:"Layout do teclado",tagline:"Sistema de recuperação, imagens de disco e implantação em rede",failed:"Falha na operação",host:"Máquina",images:"Imagens",jobs:"Tarefas de implantação",imaging:"Operações de imagem",inventory:"Inventário de armazenamento",system:"Sistema",wizard:"Assistente de operações",operation:"Operação",start:"Iniciar operação",working:"Em andamento…",completed:"Operação concluída",systemStatus:"Estado do sistema",component:"Componente",status:"Estado",configured:"Configurado",notConfigured:"Não configurado",security:"Segurança local das imagens",initializeKeys:"Inicializar chaves de segurança locais",terminal:"Acesso ao terminal",applyLayout:"Aplicar layout do teclado",layoutApplied:"Layout aplicado",layoutFailed:"Não foi possível aplicar o layout",source:"Origem",destination:"Destino",confirm:"Confirmação digitada",device:"Dispositivo",type:"Tipo",size:"Tamanho",keyboardScope:"Âmbito",keyboardScopeText:"O layout selecionado é guardado para a consola virtual Linux e o ambiente XKB do Cage/Wayland. A sessão do quiosque será reiniciada em breve para carregar o novo layout.",keyboardAppliedNotice:"O layout do teclado foi aplicado. A sessão do quiosque será reiniciada em breve.",exportP2v:"Exportar QCOW2 P2V do S3"},
fr:{refresh:"Actualiser",language:"Langue de l’interface",keyboard:"Disposition du clavier",tagline:"Appliance de secours, d’imagerie disque et de déploiement réseau",failed:"Échec de l’opération",host:"Hôte",images:"Images",jobs:"Tâches de déploiement",imaging:"Opérations d’imagerie",inventory:"Inventaire du stockage",system:"Système",wizard:"Assistant d’opérations",operation:"Opération",start:"Démarrer l’opération",working:"En cours…",completed:"Opération terminée",systemStatus:"État du système",component:"Composant",status:"État",configured:"Configuré",notConfigured:"Non configuré",security:"Sécurité locale des images",initializeKeys:"Initialiser les clés de sécurité locales",terminal:"Accès au terminal",applyLayout:"Appliquer la disposition du clavier",layoutApplied:"Disposition appliquée",layoutFailed:"Impossible d’appliquer la disposition",source:"Source",destination:"Destination",confirm:"Confirmation saisie",device:"Périphérique",type:"Type",size:"Taille",keyboardScope:"Portée",keyboardScopeText:"La disposition sélectionnée est enregistrée pour la console virtuelle Linux et l’environnement XKB de Cage/Wayland. La session kiosque redémarrera bientôt afin de charger la nouvelle disposition.",keyboardAppliedNotice:"La disposition du clavier a été appliquée. La session kiosque redémarrera bientôt.",exportP2v:"Exporter le QCOW2 P2V depuis S3"},
de:{refresh:"Aktualisieren",language:"Oberflächensprache",keyboard:"Tastaturbelegung",tagline:"Rettungs-, Datenträgerabbild- und Netzwerkbereitstellungsgerät",failed:"Vorgang fehlgeschlagen",host:"Host",images:"Abbilder",jobs:"Bereitstellungsaufträge",imaging:"Abbildvorgänge",inventory:"Speicherinventar",system:"System",wizard:"Vorgangsassistent",operation:"Vorgang",start:"Vorgang starten",working:"Wird ausgeführt…",completed:"Vorgang abgeschlossen",systemStatus:"Systemstatus",component:"Komponente",status:"Status",configured:"Konfiguriert",notConfigured:"Nicht konfiguriert",security:"Lokale Abbildsicherheit",initializeKeys:"Lokale Sicherheitsschlüssel initialisieren",terminal:"Terminalzugriff",applyLayout:"Tastaturbelegung anwenden",layoutApplied:"Tastaturbelegung angewendet",layoutFailed:"Tastaturbelegung konnte nicht angewendet werden",source:"Quelle",destination:"Ziel",confirm:"Eingegebene Bestätigung",device:"Gerät",type:"Typ",size:"Größe",keyboardScope:"Geltungsbereich",keyboardScopeText:"Die ausgewählte Belegung wird für die virtuelle Linux-Konsole und die Cage/Wayland-XKB-Umgebung gespeichert. Die Kiosksitzung wird in Kürze neu gestartet, damit die grafische Sitzung die neue Belegung lädt.",keyboardAppliedNotice:"Die Tastaturbelegung wurde übernommen. Die Kiosksitzung wird in Kürze neu gestartet.",exportP2v:"P2V-QCOW2 aus S3 exportieren"},
it:{refresh:"Aggiorna",language:"Lingua dell’interfaccia",keyboard:"Layout della tastiera",tagline:"Sistema di ripristino, immagini disco e distribuzione di rete",failed:"Operazione non riuscita",host:"Host",images:"Immagini",jobs:"Attività di distribuzione",imaging:"Operazioni sulle immagini",inventory:"Inventario archiviazione",system:"Sistema",wizard:"Procedura guidata",operation:"Operazione",start:"Avvia operazione",working:"In corso…",completed:"Operazione completata",systemStatus:"Stato del sistema",component:"Componente",status:"Stato",configured:"Configurato",notConfigured:"Non configurato",security:"Sicurezza locale delle immagini",initializeKeys:"Inizializza le chiavi di sicurezza locali",terminal:"Accesso al terminale",applyLayout:"Applica il layout della tastiera",layoutApplied:"Layout applicato",layoutFailed:"Impossibile applicare il layout",source:"Origine",destination:"Destinazione",confirm:"Conferma digitata",device:"Dispositivo",type:"Tipo",size:"Dimensione",keyboardScope:"Ambito",keyboardScopeText:"Il layout selezionato viene salvato per la console virtuale Linux e per l'ambiente XKB di Cage/Wayland. La sessione kiosk verrà riavviata a breve per caricare il nuovo layout.",keyboardAppliedNotice:"Il layout della tastiera è stato applicato. La sessione kiosk verrà riavviata a breve.",exportP2v:"Esporta QCOW2 P2V da S3"},
zh:{refresh:"刷新",language:"界面语言",keyboard:"键盘布局",tagline:"救援、磁盘映像和网络部署设备",failed:"操作失败",host:"主机",images:"映像",jobs:"部署任务",imaging:"映像操作",inventory:"存储清单",system:"系统",wizard:"操作向导",operation:"操作",start:"开始操作",working:"正在执行…",completed:"操作已完成",systemStatus:"系统状态",component:"组件",status:"状态",configured:"已配置",notConfigured:"未配置",security:"本地映像安全",initializeKeys:"初始化本地安全密钥",terminal:"终端访问",applyLayout:"应用键盘布局",layoutApplied:"键盘布局已应用",layoutFailed:"无法应用键盘布局",source:"源",destination:"目标",confirm:"输入确认",device:"设备",type:"类型",size:"大小",keyboardScope:"作用范围",keyboardScopeText:"所选布局会保存到 Linux 虚拟控制台和 Cage/Wayland XKB 环境。信息亭会话将很快重启，以便图形会话加载新布局。",keyboardAppliedNotice:"键盘布局已应用。信息亭会话将很快重启。",exportP2v:"从 S3 导出 P2V QCOW2"},
ja:{refresh:"更新",language:"インターフェース言語",keyboard:"キーボード配列",tagline:"レスキュー、ディスクイメージ、ネットワーク展開アプライアンス",failed:"操作に失敗しました",host:"ホスト",images:"イメージ",jobs:"展開ジョブ",imaging:"イメージ操作",inventory:"ストレージ一覧",system:"システム",wizard:"操作ウィザード",operation:"操作",start:"操作を開始",working:"処理中…",completed:"操作が完了しました",systemStatus:"システム状態",component:"コンポーネント",status:"状態",configured:"設定済み",notConfigured:"未設定",security:"ローカルイメージのセキュリティ",initializeKeys:"ローカルセキュリティキーを初期化",terminal:"ターミナルアクセス",applyLayout:"キーボード配列を適用",layoutApplied:"キーボード配列を適用しました",layoutFailed:"キーボード配列を適用できません",source:"ソース",destination:"宛先",confirm:"確認入力",device:"デバイス",type:"種類",size:"サイズ",keyboardScope:"適用範囲",keyboardScopeText:"選択した配列は Linux 仮想コンソールと Cage/Wayland XKB 環境に保存されます。グラフィカルセッションに新しい配列を読み込むため、キオスクセッションはまもなく再起動します。",keyboardAppliedNotice:"キーボード配列を適用しました。キオスクセッションはまもなく再起動します。",exportP2v:"S3 から P2V QCOW2 をエクスポート"},
ru:{refresh:"Обновить",language:"Язык интерфейса",keyboard:"Раскладка клавиатуры",tagline:"Система восстановления, образов дисков и сетевого развертывания",failed:"Ошибка операции",host:"Узел",images:"Образы",jobs:"Задания развертывания",imaging:"Операции с образами",inventory:"Инвентаризация хранилища",system:"Система",wizard:"Мастер операций",operation:"Операция",start:"Запустить операцию",working:"Выполняется…",completed:"Операция завершена",systemStatus:"Состояние системы",component:"Компонент",status:"Состояние",configured:"Настроено",notConfigured:"Не настроено",security:"Локальная защита образов",initializeKeys:"Инициализировать локальные ключи безопасности",terminal:"Доступ к терминалу",applyLayout:"Применить раскладку клавиатуры",layoutApplied:"Раскладка применена",layoutFailed:"Не удалось применить раскладку",source:"Источник",destination:"Назначение",confirm:"Текст подтверждения",device:"Устройство",type:"Тип",size:"Размер",keyboardScope:"Область действия",keyboardScopeText:"Выбранная раскладка сохраняется для виртуальной консоли Linux и среды XKB Cage/Wayland. Сеанс киоска вскоре перезапустится, чтобы графическая среда загрузила новую раскладку.",keyboardAppliedNotice:"Раскладка клавиатуры применена. Сеанс киоска вскоре перезапустится.",exportP2v:"Экспортировать P2V QCOW2 из S3"},
ar:{refresh:"تحديث",language:"لغة الواجهة",keyboard:"تخطيط لوحة المفاتيح",tagline:"جهاز الإنقاذ وتصوير الأقراص والنشر عبر الشبكة",failed:"فشلت العملية",host:"المضيف",images:"الصور",jobs:"مهام النشر",imaging:"عمليات التصوير",inventory:"جرد التخزين",system:"النظام",wizard:"معالج العمليات",operation:"العملية",start:"بدء العملية",working:"جارٍ التنفيذ…",completed:"اكتملت العملية",systemStatus:"حالة النظام",component:"المكوّن",status:"الحالة",configured:"تم الإعداد",notConfigured:"غير مُعد",security:"أمان الصور المحلي",initializeKeys:"تهيئة مفاتيح الأمان المحلية",terminal:"الوصول إلى الطرفية",applyLayout:"تطبيق تخطيط لوحة المفاتيح",layoutApplied:"تم تطبيق التخطيط",layoutFailed:"تعذر تطبيق التخطيط",source:"المصدر",destination:"الوجهة",confirm:"تأكيد مكتوب",device:"الجهاز",type:"النوع",size:"الحجم",keyboardScope:"النطاق",keyboardScopeText:"يُحفظ التخطيط المحدد لوحدة تحكم Linux الافتراضية وبيئة XKB في Cage/Wayland. ستُعاد جلسة الكشك قريبًا كي تحمّل الجلسة الرسومية التخطيط الجديد.",keyboardAppliedNotice:"تم تطبيق تخطيط لوحة المفاتيح. ستُعاد جلسة الكشك قريبًا.",exportP2v:"تصدير P2V QCOW2 من S3"},
tr:{refresh:"Yenile",language:"Arayüz dili",keyboard:"Klavye düzeni",tagline:"Kurtarma, disk görüntüleme ve ağ dağıtım cihazı",failed:"İşlem başarısız",host:"Ana makine",images:"Görüntüler",jobs:"Dağıtım işleri",imaging:"Görüntüleme işlemleri",inventory:"Depolama envanteri",system:"Sistem",wizard:"İşlem sihirbazı",operation:"İşlem",start:"İşlemi başlat",working:"Çalışıyor…",completed:"İşlem tamamlandı",systemStatus:"Sistem durumu",component:"Bileşen",status:"Durum",configured:"Yapılandırıldı",notConfigured:"Yapılandırılmadı",security:"Yerel görüntü güvenliği",initializeKeys:"Yerel güvenlik anahtarlarını başlat",terminal:"Terminal erişimi",applyLayout:"Klavye düzenini uygula",layoutApplied:"Klavye düzeni uygulandı",layoutFailed:"Klavye düzeni uygulanamadı",source:"Kaynak",destination:"Hedef",confirm:"Yazılı onay",device:"Aygıt",type:"Tür",size:"Boyut",keyboardScope:"Kapsam",keyboardScopeText:"Seçilen düzen Linux sanal konsolu ve Cage/Wayland XKB ortamı için kaydedilir. Grafik oturumunun yeni düzeni yüklemesi için kiosk oturumu kısa süre içinde yeniden başlatılır.",keyboardAppliedNotice:"Klavye düzeni uygulandı. Kiosk oturumu kısa süre içinde yeniden başlatılacak.",exportP2v:"S3'ten P2V QCOW2 dışa aktar"}
};


const COMPLETION_TRANSLATIONS = {
  es: {
    manifests:"Imágenes locales con manifiesto", recordedJobs:"Trabajos registrados y estado de recuperación", loading:"Cargando Feclora", chooseOperation:"Elige una operación, revisa los dispositivos seleccionados y confirma expresamente cada destino destructivo.", safety:"Modelo de seguridad", storageSafety:"Feclora vuelve a comprobar la identidad de los dispositivos, los montajes, el uso del sistema, la geometría y la integridad de las imágenes justo antes de escribir. La selección en el navegador no constituye autorización.", generateSecurity:"Genera una CA local de Feclora y, opcionalmente, una identidad age. Las claves privadas permanecen en este equipo; después podrás cifrar las imágenes capturadas.", capability:"Capacidad", ready:"Preparado", notInitialized:"No inicializado", terminalHelp:"Para configurar el sistema, diagnosticar la red y realizar tareas avanzadas, utiliza la página Terminal de Cockpit. No eludas las comprobaciones de seguridad de Feclora.", footer:"Todas las operaciones de almacenamiento utilizan los motores Python compartidos de Feclora. Cockpit es la interfaz principal.", chooseLayout:"Elige la distribución física del teclado independientemente del idioma de la interfaz. Este ajuste actualiza el mapa persistente de la consola virtual Linux y la consola de texto activa.", currentKeymap:"Mapa de teclado Linux actual", scope:"Ámbito", consoleOnly:"La implementación actual configura la consola virtual Linux. La sesión gráfica Cage/Wayland aún requiere una integración XKB independiente; este control todavía no cambia esa sesión.", operationLabels:"Etiquetas de operación", storageDevices:"Discos y particiones", model:"Modelo", filesystem:"Sistema de archivos", mounts:"Puntos de montaje"
  },
  ca: {
    manifests:"Imatges locals amb manifest", recordedJobs:"Treballs registrats i estat de recuperació", loading:"S'està carregant Feclora", chooseOperation:"Tria una operació, revisa els dispositius seleccionats i confirma explícitament cada destinació destructiva.", safety:"Model de seguretat", storageSafety:"Feclora torna a comprovar la identitat dels dispositius, els muntatges, l'ús del sistema, la geometria i la integritat de les imatges just abans d'escriure. La selecció al navegador no és una autorització.", generateSecurity:"Genera una CA local de Feclora i, opcionalment, una identitat age. Les claus privades romanen en aquest equip; després podràs xifrar les imatges capturades.", capability:"Capacitat", ready:"Preparat", notInitialized:"No inicialitzat", terminalHelp:"Per configurar el sistema, diagnosticar la xarxa i fer tasques avançades, utilitza la pàgina Terminal de Cockpit. No esquivis les comprovacions de seguretat de Feclora.", footer:"Totes les operacions d'emmagatzematge utilitzen els motors Python compartits de Feclora. Cockpit és la interfície principal.", chooseLayout:"Tria la disposició física del teclat independentment de l'idioma de la interfície. Aquest ajust actualitza el mapa persistent de la consola virtual Linux i la consola de text activa.", currentKeymap:"Mapa de teclat Linux actual", scope:"Àmbit", consoleOnly:"La implementació actual configura la consola virtual Linux. La sessió gràfica Cage/Wayland encara necessita una integració XKB independent; aquest control encara no modifica aquella sessió.", operationLabels:"Etiquetes de les operacions", storageDevices:"Discos i particions", model:"Model", filesystem:"Sistema de fitxers", mounts:"Punts de muntatge"
  },
  gl: {
    manifests:"Imaxes locais con manifesto", recordedJobs:"Traballos rexistrados e estado de recuperación", loading:"Cargando Feclora", chooseOperation:"Escolle unha operación, revisa os dispositivos e confirma expresamente cada destino destrutivo.", safety:"Modelo de seguridade", storageSafety:"Feclora volve comprobar a identidade dos dispositivos, as montaxes, o uso do sistema, a xeometría e a integridade das imaxes xusto antes de escribir. A selección no navegador non é unha autorización.", generateSecurity:"Xera unha CA local de Feclora e, opcionalmente, unha identidade age. As claves privadas permanecen neste equipo; despois poderás cifrar as imaxes capturadas.", capability:"Capacidade", ready:"Preparado", notInitialized:"Sen inicializar", terminalHelp:"Para configurar o sistema, diagnosticar a rede e realizar tarefas avanzadas, utiliza a páxina Terminal de Cockpit. Non evites as comprobacións de seguridade de Feclora.", footer:"Todas as operacións de almacenamento utilizan os motores Python compartidos de Feclora. Cockpit é a interface principal.", chooseLayout:"Escolle a distribución física do teclado independentemente do idioma da interface. Este axuste actualiza o mapa persistente da consola virtual Linux e a consola de texto activa.", currentKeymap:"Mapa de teclado Linux actual", scope:"Ámbito", consoleOnly:"A implementación actual configura a consola virtual Linux. A sesión gráfica Cage/Wayland aínda precisa unha integración XKB independente; este control aínda non modifica esa sesión.", operationLabels:"Etiquetas das operacións", storageDevices:"Discos e particións", model:"Modelo", filesystem:"Sistema de ficheiros", mounts:"Puntos de montaxe"
  },
  eu: {
    manifests:"Manifestua duten irudi lokalak", recordedJobs:"Erregistratutako lanak eta berreskuratze-egoera", loading:"Feclora kargatzen", chooseOperation:"Aukeratu eragiketa bat, berrikusi hautatutako gailuak eta berariaz berretsi suntsitzailea izan daitekeen helmuga bakoitza.", safety:"Segurtasun-eredua", storageSafety:"Feclorak gailuen identitatea, muntaketak, sistemaren erabilera, geometria eta irudien osotasuna berriro egiaztatzen ditu idatzi aurretik. Nabigatzaileko hautaketa ez da baimen gisa hartzen.", generateSecurity:"Sortu Fecloraren CA lokala eta, aukeran, age identitatea. Gako pribatuak ordenagailu honetan geratzen dira; harrapatutako irudiak zifratu ahal izango dituzu.", capability:"Gaitasuna", ready:"Prest", notInitialized:"Hasieratu gabe", terminalHelp:"Sistema konfiguratzeko, sarea diagnostikatzeko eta administrazio aurreratua egiteko, erabili Cockpit-eko Terminal orria. Ez saihestu Fecloraren biltegiratze-segurtasun egiaztapenak.", footer:"Biltegiratze-eragiketa guztiek Fecloraren Python motor partekatuak erabiltzen dituzte. Cockpit da operadorearen interfaze nagusia.", chooseLayout:"Aukeratu teklatuaren diseinu fisikoa interfazearen hizkuntzatik bereizita. Ezarpen honek Linux kontsola birtualaren mapa iraunkorra eta testu-kontsola aktiboa eguneratzen ditu.", currentKeymap:"Uneko Linux teklatu-mapa", scope:"Esparrua", consoleOnly:"Uneko inplementazioak Linux kontsola birtuala konfiguratzen du. Cage/Wayland saio grafikoak XKB integrazio bereizia behar du oraindik; kontrol honek ez du saio hori aldatzen.", operationLabels:"Eragiketa-izenak", storageDevices:"Diskoak eta partizioak", model:"Modeloa", filesystem:"Fitxategi-sistema", mounts:"Muntatze-puntuak"
  },
  pt: {
    manifests:"Imagens locais com manifesto", recordedJobs:"Tarefas registadas e estado de recuperação", loading:"A carregar o Feclora", chooseOperation:"Escolha uma operação, reveja os dispositivos selecionados e confirme explicitamente cada destino destrutivo.", safety:"Modelo de segurança", storageSafety:"O Feclora volta a verificar a identidade dos dispositivos, as montagens, a utilização pelo sistema, a geometria e a integridade das imagens imediatamente antes de escrever. A seleção no navegador não constitui autorização.", generateSecurity:"Gere uma CA local do Feclora e, opcionalmente, uma identidade age. As chaves privadas permanecem neste computador; depois poderá encriptar as imagens capturadas.", capability:"Capacidade", ready:"Pronto", notInitialized:"Não inicializado", terminalHelp:"Para configurar o sistema, diagnosticar a rede e executar tarefas avançadas, utilize a página Terminal do Cockpit. Não contorne as verificações de segurança do Feclora.", footer:"Todas as operações de armazenamento utilizam os motores Python partilhados do Feclora. O Cockpit é a interface principal.", chooseLayout:"Escolha o mapa físico do teclado independentemente do idioma da interface. Esta definição atualiza o mapa persistente da consola virtual Linux e a consola de texto ativa.", currentKeymap:"Mapa de teclado Linux atual", scope:"Âmbito", consoleOnly:"A implementação atual configura a consola virtual Linux. A sessão gráfica Cage/Wayland ainda necessita de integração XKB própria; este controlo ainda não altera essa sessão.", operationLabels:"Etiquetas das operações", storageDevices:"Discos e partições", model:"Modelo", filesystem:"Sistema de ficheiros", mounts:"Pontos de montagem"
  },
  fr: {
    manifests:"Images locales avec manifeste", recordedJobs:"Tâches enregistrées et état de récupération", loading:"Chargement de Feclora", chooseOperation:"Choisissez une opération, vérifiez les périphériques sélectionnés et confirmez explicitement chaque destination destructive.", safety:"Modèle de sécurité", storageSafety:"Feclora revérifie l’identité des périphériques, les montages, l’utilisation par le système, la géométrie et l’intégrité des images juste avant toute écriture. Une sélection dans le navigateur ne constitue pas une autorisation.", generateSecurity:"Générez une autorité de certification locale Feclora et, facultativement, une identité age. Les clés privées restent sur cette machine ; les images capturées pourront ensuite être chiffrées.", capability:"Capacité", ready:"Prêt", notInitialized:"Non initialisé", terminalHelp:"Pour configurer le système, diagnostiquer le réseau et effectuer des tâches avancées, utilisez la page Terminal de Cockpit. Ne contournez pas les contrôles de sécurité du stockage Feclora.", footer:"Toutes les opérations de stockage utilisent les moteurs Python partagés de Feclora. Cockpit est l’interface principale de l’opérateur.", chooseLayout:"Choisissez la disposition physique du clavier indépendamment de la langue de l’interface. Ce réglage met à jour la disposition persistante de la console virtuelle Linux et la console texte active.", currentKeymap:"Disposition actuelle du clavier Linux", scope:"Portée", consoleOnly:"L’implémentation actuelle configure la console virtuelle Linux. La session graphique Cage/Wayland nécessite encore une intégration XKB distincte ; ce contrôle ne modifie pas encore cette session.", operationLabels:"Libellés des opérations", storageDevices:"Disques et partitions", model:"Modèle", filesystem:"Système de fichiers", mounts:"Points de montage"
  },
  de: {
    manifests:"Lokale Images mit Manifest", recordedJobs:"Gespeicherte Aufträge und Wiederherstellungsstatus", loading:"Feclora wird geladen", chooseOperation:"Wählen Sie einen Vorgang, prüfen Sie die ausgewählten Geräte und bestätigen Sie jedes destruktive Ziel ausdrücklich.", safety:"Sicherheitsmodell", storageSafety:"Feclora prüft Geräteidentität, Einbindungen, Systemverwendung, Geometrie und Image-Integrität unmittelbar vor dem Schreiben erneut. Eine Browserauswahl gilt nicht als Autorisierung.", generateSecurity:"Erstellen Sie eine lokale Feclora-CA und optional eine age-Identität. Private Schlüssel verbleiben auf diesem Rechner; erfasste Images können anschließend verschlüsselt werden.", capability:"Funktion", ready:"Bereit", notInitialized:"Nicht initialisiert", terminalHelp:"Verwenden Sie für Systemeinrichtung, Netzwerkdiagnose und erweiterte Verwaltung die Terminal-Seite von Cockpit. Umgehen Sie nicht die Speichersicherheitsprüfungen von Feclora.", footer:"Alle Speicheroperationen verwenden die gemeinsamen Python-Engines von Feclora. Cockpit ist die primäre Bedienoberfläche.", chooseLayout:"Wählen Sie das physische Tastaturlayout unabhängig von der Oberflächensprache. Diese Einstellung aktualisiert das persistente Linux-Virtualkonsolenlayout und die aktive Textkonsole.", currentKeymap:"Aktuelles Linux-Tastaturlayout", scope:"Geltungsbereich", consoleOnly:"Die aktuelle Implementierung konfiguriert die Linux-Virtualkonsole. Für die grafische Cage/Wayland-Sitzung ist weiterhin eine separate XKB-Integration erforderlich; diese Einstellung ändert die Sitzung noch nicht.", operationLabels:"Operationsbezeichnungen", storageDevices:"Laufwerke und Partitionen", model:"Modell", filesystem:"Dateisystem", mounts:"Einhängepunkte"
  },
  it: {
    manifests:"Immagini locali con manifest", recordedJobs:"Operazioni registrate e stato di ripristino", loading:"Caricamento di Feclora", chooseOperation:"Scegli un'operazione, controlla i dispositivi selezionati e conferma esplicitamente ogni destinazione distruttiva.", safety:"Modello di sicurezza", storageSafety:"Feclora ricontrolla identità dei dispositivi, montaggi, uso da parte del sistema, geometria e integrità delle immagini immediatamente prima della scrittura. La selezione nel browser non costituisce autorizzazione.", generateSecurity:"Genera una CA locale Feclora e, facoltativamente, un'identità age. Le chiavi private restano su questo computer; le immagini acquisite potranno poi essere cifrate.", capability:"Funzionalità", ready:"Pronto", notInitialized:"Non inizializzato", terminalHelp:"Per configurazione del sistema, diagnostica di rete e amministrazione avanzata, usa la pagina Terminale di Cockpit. Non aggirare i controlli di sicurezza dello storage Feclora.", footer:"Tutte le operazioni di archiviazione utilizzano i motori Python condivisi di Feclora. Cockpit è l'interfaccia principale dell'operatore.", chooseLayout:"Scegli la mappatura fisica della tastiera indipendentemente dalla lingua dell'interfaccia. Questa impostazione aggiorna la mappa persistente della console virtuale Linux e la console testuale attiva.", currentKeymap:"Mappa tastiera Linux attuale", scope:"Ambito", consoleOnly:"L'implementazione attuale configura la console virtuale Linux. La sessione grafica Cage/Wayland richiede ancora un'integrazione XKB separata; questo controllo non modifica ancora tale sessione.", operationLabels:"Etichette delle operazioni", storageDevices:"Dischi e partizioni", model:"Modello", filesystem:"File system", mounts:"Punti di montaggio"
  },
  zh: {
    manifests:"带清单的本地映像", recordedJobs:"已记录的任务和恢复状态", loading:"正在加载 Feclora", chooseOperation:"选择操作，检查所选设备，并明确确认每个具有破坏性的目标。", safety:"安全模型", storageSafety:"Feclora 会在写入前立即重新检查块设备身份、挂载和系统占用状态、几何参数及映像完整性。浏览器中的选择本身不构成授权。", generateSecurity:"生成本地 Feclora CA，并可选生成 age 身份。私钥保留在此计算机上；之后可按需加密捕获的映像。", capability:"能力", ready:"就绪", notInitialized:"尚未初始化", terminalHelp:"系统设置、网络诊断和高级管理请使用 Cockpit 的终端页面。请勿绕过 Feclora 的存储安全检查。", footer:"所有存储操作均使用 Feclora 共享的 Python 引擎。Cockpit 是主要操作界面。", chooseLayout:"独立于界面语言选择物理键盘布局。此设置会更新持久化的 Linux 虚拟控制台键盘映射和当前文本控制台。", currentKeymap:"当前 Linux 键盘映射", scope:"范围", consoleOnly:"当前实现配置 Linux 虚拟控制台。Cage/Wayland 图形会话仍需单独集成 XKB；此控件目前不会更改该会话。", operationLabels:"操作标签", storageDevices:"块设备和分区", model:"型号", filesystem:"文件系统", mounts:"挂载点"
  },
  ja: {
    manifests:"マニフェスト付きローカルイメージ", recordedJobs:"記録済みジョブと復旧状態", loading:"Feclora を読み込み中", chooseOperation:"操作を選択し、選択したデバイスを確認して、破壊的な対象をそれぞれ明示的に承認してください。", safety:"安全性モデル", storageSafety:"Feclora は書き込み直前に、ブロックデバイスの識別情報、マウントとシステム使用状況、ジオメトリ、イメージの整合性を再確認します。ブラウザーでの選択だけでは承認になりません。", generateSecurity:"ローカル Feclora CA と、任意で age ID を生成します。秘密鍵はこのマシンに保持され、取得したイメージは必要に応じて暗号化できます。", capability:"機能", ready:"準備完了", notInitialized:"未初期化", terminalHelp:"システム設定、ネットワーク診断、高度な管理には Cockpit の Terminal ページを使用してください。Feclora のストレージ安全確認を回避しないでください。", footer:"すべてのストレージ操作は Feclora 共通の Python エンジンを使用します。Cockpit が主な操作インターフェースです。", chooseLayout:"インターフェース言語とは独立して物理キーボード配列を選択します。この設定は永続的な Linux 仮想コンソールのキーマップとアクティブなテキストコンソールを更新します。", currentKeymap:"現在の Linux キーマップ", scope:"適用範囲", consoleOnly:"現在の実装は Linux 仮想コンソールを設定します。Cage/Wayland グラフィカルセッションには別途 XKB 統合が必要であり、この設定はまだそのセッションを変更しません。", operationLabels:"操作ラベル", storageDevices:"ブロックデバイスとパーティション", model:"モデル", filesystem:"ファイルシステム", mounts:"マウントポイント"
  },
  ru: {
    manifests:"Локальные образы с манифестом", recordedJobs:"Записанные задания и состояние восстановления", loading:"Загрузка Feclora", chooseOperation:"Выберите операцию, проверьте выбранные устройства и явно подтвердите каждую разрушающую цель.", safety:"Модель безопасности", storageSafety:"Перед записью Feclora повторно проверяет идентификаторы блочных устройств, точки монтирования и использование системой, геометрию и целостность образа. Выбор в браузере сам по себе не является разрешением.", generateSecurity:"Создайте локальный центр сертификации Feclora и, при необходимости, идентификатор age. Закрытые ключи остаются на этом компьютере; захваченные образы можно зашифровать.", capability:"Возможности", ready:"Готово", notInitialized:"Не инициализировано", terminalHelp:"Для настройки системы, диагностики сети и расширенного администрирования используйте страницу Terminal в Cockpit. Не обходите проверки безопасности хранилища Feclora.", footer:"Все операции с хранилищем используют общие движки Python Feclora. Cockpit — основной интерфейс оператора.", chooseLayout:"Выберите физическую раскладку клавиатуры независимо от языка интерфейса. Эта настройка обновляет постоянную раскладку виртуальной консоли Linux и активную текстовую консоль.", currentKeymap:"Текущая раскладка Linux", scope:"Область действия", consoleOnly:"Текущая реализация настраивает виртуальную консоль Linux. Для графического сеанса Cage/Wayland по-прежнему требуется отдельная интеграция XKB; этот параметр пока не меняет графический сеанс.", operationLabels:"Названия операций", storageDevices:"Блочные устройства и разделы", model:"Модель", filesystem:"Файловая система", mounts:"Точки монтирования"
  },
  ar: {
    manifests:"صور محلية مدعومة ببيان", recordedJobs:"المهام المسجلة وحالة الاسترداد", loading:"جارٍ تحميل Feclora", chooseOperation:"اختر عملية، وراجع الأجهزة المحددة، وأكّد صراحةً كل وجهة مدمّرة.", safety:"نموذج الأمان", storageSafety:"يعيد Feclora التحقق من هوية أجهزة الكتل وحالات التحميل واستخدام النظام والهندسة وسلامة الصور مباشرةً قبل الكتابة. لا يُعد الاختيار في المتصفح تفويضًا بحد ذاته.", generateSecurity:"أنشئ سلطة تصديق محلية لـ Feclora وهوية age اختيارية. تبقى المفاتيح الخاصة على هذا الجهاز، ويمكن تشفير الصور الملتقطة لاحقًا.", capability:"الإمكانات", ready:"جاهز", notInitialized:"لم تتم التهيئة", terminalHelp:"لإعداد النظام وتشخيص الشبكة والإدارة المتقدمة، استخدم صفحة Terminal في Cockpit. لا تتجاوز فحوصات أمان التخزين في Feclora.", footer:"تستخدم جميع عمليات التخزين محركات Python المشتركة في Feclora. Cockpit هي واجهة التشغيل الأساسية.", chooseLayout:"اختر تخطيط لوحة المفاتيح الفعلي بشكل مستقل عن لغة الواجهة. يحدّث هذا الإعداد خريطة مفاتيح وحدة تحكم Linux الافتراضية الدائمة ووحدة التحكم النصية النشطة.", currentKeymap:"خريطة مفاتيح Linux الحالية", scope:"النطاق", consoleOnly:"يهيئ التنفيذ الحالي وحدة تحكم Linux الافتراضية. لا تزال جلسة Cage/Wayland الرسومية تحتاج إلى تكامل XKB منفصل؛ ولا يغيّر هذا التحكم تلك الجلسة حاليًا.", operationLabels:"تسميات العمليات", storageDevices:"أجهزة الكتل والأقسام", model:"الطراز", filesystem:"نظام الملفات", mounts:"نقاط التحميل"
  },
  tr: {
    manifests:"Manifest destekli yerel kalıplar", recordedJobs:"Kaydedilen işler ve kurtarma durumu", loading:"Feclora yükleniyor", chooseOperation:"Bir işlem seçin, seçilen aygıtları inceleyin ve yıkıcı her hedefi açıkça onaylayın.", safety:"Güvenlik modeli", storageSafety:"Feclora yazmadan hemen önce blok aygıtı kimliğini, bağlama ve sistem kullanım durumunu, geometrisini ve görüntü bütünlüğünü yeniden denetler. Tarayıcıdaki seçim tek başına yetkilendirme sayılmaz.", generateSecurity:"Yerel bir Feclora CA ve isteğe bağlı age kimliği oluşturun. Özel anahtarlar bu makinede kalır; alınan görüntüler daha sonra şifrelenebilir.", capability:"Yetenek", ready:"Hazır", notInitialized:"Başlatılmadı", terminalHelp:"Sistem kurulumu, ağ tanılama ve gelişmiş yönetim için Cockpit Terminal sayfasını kullanın. Feclora depolama güvenliği denetimlerini atlamayın.", footer:"Tüm depolama işlemleri Feclora'nın ortak Python motorlarını kullanır. Cockpit birincil operatör arayüzüdür.", chooseLayout:"Fiziksel klavye düzenini arayüz dilinden bağımsız seçin. Bu ayar kalıcı Linux sanal konsol tuş haritasını ve etkin metin konsolunu günceller.", currentKeymap:"Geçerli Linux tuş haritası", scope:"Kapsam", consoleOnly:"Geçerli uygulama Linux sanal konsolunu yapılandırır. Cage/Wayland grafik oturumu için ayrıca XKB entegrasyonu gerekir; bu denetim henüz o oturumu değiştirmez.", operationLabels:"İşlem etiketleri", storageDevices:"Blok aygıtları ve bölümler", model:"Model", filesystem:"Dosya sistemi", mounts:"Bağlama noktaları"
  }
};
for (const [language, entries] of Object.entries(COMPLETION_TRANSLATIONS)) {
  Object.assign(DICTS[language], entries);
}


const EXTRA_TRANSLATIONS = {
  en: {
    tabImages:"Image repository", tabRemoteJobs:"Remote jobs", tabHistory:"Deployment history", tabRepositories:"Remote repositories", tabOperationLog:"Operation log", tabNetwork:"Network (Server / Client)",
    opCaptureDisk:"Create a whole-disk image", opCaptureP2v:"Convert physical disk to QCOW2 (P2V)", opExportP2v:"Export P2V QCOW2 from S3", opRecoveryIso:"Build a self-contained recovery ISO", opCapturePartition:"Create a partition image", opCaptureVolume:"Create a logical-volume image", opRestoreDisk:"Restore a whole-disk image", opRestorePartition:"Restore a partition image", opRestoreVolume:"Restore a logical-volume image", opCloneDisk:"Clone disk to disk", opClonePartition:"Clone partition to partition",
    availableImages:"Available images", imageRepository:"Image repository", extractPartition:"Extract a partition from a whole-disk image", createRemoteJob:"Create a remote deployment job", deploymentJournals:"Deployment journals", remoteImageRepositories:"Remote image repositories", localOperationHistory:"Local operation history"
  },
  es: {
    tabImages:"Repositorio de imágenes",tabRemoteJobs:"Trabajos remotos",tabHistory:"Historial de despliegues",tabRepositories:"Repositorios remotos",tabOperationLog:"Registro de operaciones",tabNetwork:"Red (Servidor / Cliente)",
    opCaptureDisk:"Crear imagen de disco completo",opCaptureP2v:"Convertir disco físico a QCOW2 (P2V)",opExportP2v:"Exportar QCOW2 P2V desde S3",opRecoveryIso:"Crear ISO de recuperación autónoma",opCapturePartition:"Crear imagen de partición",opCaptureVolume:"Crear imagen de volumen lógico",opRestoreDisk:"Restaurar disco completo",opRestorePartition:"Restaurar partición",opRestoreVolume:"Restaurar volumen lógico",opCloneDisk:"Clonar disco a disco",opClonePartition:"Clonar partición a partición",
    availableImages:"Imágenes disponibles",imageRepository:"Repositorio de imágenes",extractPartition:"Extraer una partición de una imagen de disco completo",createRemoteJob:"Crear un trabajo de despliegue remoto",deploymentJournals:"Registros de despliegue",remoteImageRepositories:"Repositorios remotos de imágenes",localOperationHistory:"Historial local de operaciones"
  },
  ca: {
    tabImages:"Repositori d'imatges",tabRemoteJobs:"Treballs remots",tabHistory:"Historial de desplegaments",tabRepositories:"Repositoris remots",tabOperationLog:"Registre d'operacions",tabNetwork:"Xarxa (Servidor / Client)",
    opCaptureDisk:"Crea una imatge de disc sencer",opCaptureP2v:"Converteix un disc físic a QCOW2 (P2V)",opExportP2v:"Exporta QCOW2 P2V des de S3",opRecoveryIso:"Crea una ISO de recuperació autònoma",opCapturePartition:"Crea una imatge de partició",opCaptureVolume:"Crea una imatge de volum lògic",opRestoreDisk:"Restaura un disc sencer",opRestorePartition:"Restaura una partició",opRestoreVolume:"Restaura un volum lògic",opCloneDisk:"Clona un disc a un altre disc",opClonePartition:"Clona una partició a una altra",
    availableImages:"Imatges disponibles",imageRepository:"Repositori d'imatges",extractPartition:"Extreu una partició d'una imatge de disc sencer",createRemoteJob:"Crea un treball de desplegament remot",deploymentJournals:"Registres de desplegament",remoteImageRepositories:"Repositoris remots d'imatges",localOperationHistory:"Historial local d'operacions"
  },
  gl: {
    tabImages:"Repositorio de imaxes",tabRemoteJobs:"Traballos remotos",tabHistory:"Historial de despregamentos",tabRepositories:"Repositorios remotos",tabOperationLog:"Rexistro de operacións",tabNetwork:"Rede (Servidor / Cliente)",
    opCaptureDisk:"Crear imaxe de disco completo",opCaptureP2v:"Converter disco físico a QCOW2 (P2V)",opExportP2v:"Exportar QCOW2 P2V desde S3",opRecoveryIso:"Crear ISO de recuperación autónoma",opCapturePartition:"Crear imaxe de partición",opCaptureVolume:"Crear imaxe de volume lóxico",opRestoreDisk:"Restaurar disco completo",opRestorePartition:"Restaurar partición",opRestoreVolume:"Restaurar volume lóxico",opCloneDisk:"Clonar disco a disco",opClonePartition:"Clonar partición a partición",
    availableImages:"Imaxes dispoñibles",imageRepository:"Repositorio de imaxes",extractPartition:"Extraer unha partición dunha imaxe de disco completo",createRemoteJob:"Crear un traballo de despregamento remoto",deploymentJournals:"Rexistros de despregamento",remoteImageRepositories:"Repositorios remotos de imaxes",localOperationHistory:"Historial local de operacións"
  },
  eu: {
    tabImages:"Irudi-biltegia",tabRemoteJobs:"Urruneko lanak",tabHistory:"Hedapen-historia",tabRepositories:"Urruneko biltegiak",tabOperationLog:"Eragiketen erregistroa",tabNetwork:"Sarea (zerbitzaria / bezeroa)",
    opCaptureDisk:"Sortu disko osoko irudia",opCaptureP2v:"Bihurtu disko fisikoa QCOW2ra (P2V)",opExportP2v:"Esportatu P2V QCOW2 S3tik",opRecoveryIso:"Sortu berreskuratze-ISO autonomoa",opCapturePartition:"Sortu partizio-irudia",opCaptureVolume:"Sortu bolumen logikoaren irudia",opRestoreDisk:"Berrezarri disko osoa",opRestorePartition:"Berrezarri partizioa",opRestoreVolume:"Berrezarri bolumen logikoa",opCloneDisk:"Klonatu diskoa diskora",opClonePartition:"Klonatu partizioa partiziora",
    availableImages:"Eskuragarri dauden irudiak",imageRepository:"Irudi-biltegia",extractPartition:"Atera partizio bat disko osoko iruditik",createRemoteJob:"Sortu urruneko hedapen-lana",deploymentJournals:"Hedapen-egunkariak",remoteImageRepositories:"Urruneko irudi-biltegiak",localOperationHistory:"Eragiketen historia lokala"
  },
  pt: {
    tabImages:"Repositório de imagens",tabRemoteJobs:"Tarefas remotas",tabHistory:"Histórico de implementações",tabRepositories:"Repositórios remotos",tabOperationLog:"Registo de operações",tabNetwork:"Rede (Servidor / Cliente)",
    opCaptureDisk:"Criar imagem de disco completo",opCaptureP2v:"Converter disco físico para QCOW2 (P2V)",opExportP2v:"Exportar QCOW2 P2V do S3",opRecoveryIso:"Criar ISO de recuperação autónoma",opCapturePartition:"Criar imagem de partição",opCaptureVolume:"Criar imagem de volume lógico",opRestoreDisk:"Restaurar disco completo",opRestorePartition:"Restaurar partição",opRestoreVolume:"Restaurar volume lógico",opCloneDisk:"Clonar disco para disco",opClonePartition:"Clonar partição para partição",
    availableImages:"Imagens disponíveis",imageRepository:"Repositório de imagens",extractPartition:"Extrair uma partição de uma imagem de disco completo",createRemoteJob:"Criar uma tarefa de implementação remota",deploymentJournals:"Registos de implementação",remoteImageRepositories:"Repositórios remotos de imagens",localOperationHistory:"Histórico local de operações"
  },
  fr: {
    tabImages:"Dépôt d’images",tabRemoteJobs:"Tâches distantes",tabHistory:"Historique des déploiements",tabRepositories:"Dépôts distants",tabOperationLog:"Journal des opérations",tabNetwork:"Réseau (Serveur / Client)",
    opCaptureDisk:"Créer une image de disque entier",opCaptureP2v:"Convertir un disque physique en QCOW2 (P2V)",opExportP2v:"Exporter le QCOW2 P2V depuis S3",opRecoveryIso:"Créer un ISO de récupération autonome",opCapturePartition:"Créer une image de partition",opCaptureVolume:"Créer une image de volume logique",opRestoreDisk:"Restaurer un disque entier",opRestorePartition:"Restaurer une partition",opRestoreVolume:"Restaurer un volume logique",opCloneDisk:"Cloner un disque vers un disque",opClonePartition:"Cloner une partition vers une partition",
    availableImages:"Images disponibles",imageRepository:"Dépôt d’images",extractPartition:"Extraire une partition d’une image de disque entier",createRemoteJob:"Créer une tâche de déploiement distante",deploymentJournals:"Journaux de déploiement",remoteImageRepositories:"Dépôts d’images distants",localOperationHistory:"Historique local des opérations"
  },
  de: {
    tabImages:"Image-Repository",tabRemoteJobs:"Remote-Aufträge",tabHistory:"Deployment-Verlauf",tabRepositories:"Remote-Repositories",tabOperationLog:"Betriebsprotokoll",tabNetwork:"Netzwerk (Server / Client)",
    opCaptureDisk:"Gesamtes Laufwerk als Image sichern",opCaptureP2v:"Physisches Laufwerk in QCOW2 konvertieren (P2V)",opExportP2v:"P2V-QCOW2 aus S3 exportieren",opRecoveryIso:"Eigenständige Recovery-ISO erstellen",opCapturePartition:"Partitionsimage erstellen",opCaptureVolume:"Image eines logischen Volumes erstellen",opRestoreDisk:"Gesamtes Laufwerk wiederherstellen",opRestorePartition:"Partition wiederherstellen",opRestoreVolume:"Logisches Volume wiederherstellen",opCloneDisk:"Laufwerk auf Laufwerk klonen",opClonePartition:"Partition auf Partition klonen",
    availableImages:"Verfügbare Images",imageRepository:"Image-Repository",extractPartition:"Partition aus einem Laufwerksimage extrahieren",createRemoteJob:"Remote-Deployment-Auftrag erstellen",deploymentJournals:"Deployment-Protokolle",remoteImageRepositories:"Remote-Image-Repositories",localOperationHistory:"Lokaler Betriebsverlauf"
  },
  it: {
    tabImages:"Archivio immagini",tabRemoteJobs:"Operazioni remote",tabHistory:"Cronologia distribuzioni",tabRepositories:"Archivi remoti",tabOperationLog:"Registro operazioni",tabNetwork:"Rete (Server / Client)",
    opCaptureDisk:"Crea un'immagine dell'intero disco",opCaptureP2v:"Converti disco fisico in QCOW2 (P2V)",opExportP2v:"Esporta QCOW2 P2V da S3",opRecoveryIso:"Crea ISO di ripristino autonoma",opCapturePartition:"Crea immagine di partizione",opCaptureVolume:"Crea immagine di volume logico",opRestoreDisk:"Ripristina l'intero disco",opRestorePartition:"Ripristina partizione",opRestoreVolume:"Ripristina volume logico",opCloneDisk:"Clona disco su disco",opClonePartition:"Clona partizione su partizione",
    availableImages:"Immagini disponibili",imageRepository:"Archivio immagini",extractPartition:"Estrai una partizione da un'immagine dell'intero disco",createRemoteJob:"Crea un'operazione di distribuzione remota",deploymentJournals:"Registri di distribuzione",remoteImageRepositories:"Archivi remoti di immagini",localOperationHistory:"Cronologia locale delle operazioni"
  },
  zh: {
    tabImages:"映像仓库",tabRemoteJobs:"远程任务",tabHistory:"部署历史",tabRepositories:"远程仓库",tabOperationLog:"操作日志",tabNetwork:"网络（服务器 / 客户端）",
    opCaptureDisk:"创建整盘映像",opCaptureP2v:"将物理磁盘转换为 QCOW2（P2V）",opExportP2v:"从 S3 导出 P2V QCOW2",opRecoveryIso:"创建独立恢复 ISO",opCapturePartition:"创建分区映像",opCaptureVolume:"创建逻辑卷映像",opRestoreDisk:"恢复整盘",opRestorePartition:"恢复分区",opRestoreVolume:"恢复逻辑卷",opCloneDisk:"磁盘克隆到磁盘",opClonePartition:"分区克隆到分区",
    availableImages:"可用映像",imageRepository:"映像仓库",extractPartition:"从整盘映像中提取分区",createRemoteJob:"创建远程部署任务",deploymentJournals:"部署日志",remoteImageRepositories:"远程映像仓库",localOperationHistory:"本地操作历史"
  },
  ja: {
    tabImages:"イメージリポジトリ",tabRemoteJobs:"リモートジョブ",tabHistory:"展開履歴",tabRepositories:"リモートリポジトリ",tabOperationLog:"操作ログ",tabNetwork:"ネットワーク（サーバー / クライアント）",
    opCaptureDisk:"ディスク全体のイメージを作成",opCaptureP2v:"物理ディスクを QCOW2 に変換（P2V）",opExportP2v:"S3 から P2V QCOW2 をエクスポート",opRecoveryIso:"スタンドアロン復旧 ISO を作成",opCapturePartition:"パーティションイメージを作成",opCaptureVolume:"論理ボリュームイメージを作成",opRestoreDisk:"ディスク全体を復元",opRestorePartition:"パーティションを復元",opRestoreVolume:"論理ボリュームを復元",opCloneDisk:"ディスクを別ディスクに複製",opClonePartition:"パーティションを複製",
    availableImages:"利用可能なイメージ",imageRepository:"イメージリポジトリ",extractPartition:"ディスク全体のイメージからパーティションを抽出",createRemoteJob:"リモート展開ジョブを作成",deploymentJournals:"展開ジャーナル",remoteImageRepositories:"リモートイメージリポジトリ",localOperationHistory:"ローカル操作履歴"
  },
  ru: {
    tabImages:"Хранилище образов",tabRemoteJobs:"Удалённые задания",tabHistory:"История развёртываний",tabRepositories:"Удалённые хранилища",tabOperationLog:"Журнал операций",tabNetwork:"Сеть (сервер / клиент)",
    opCaptureDisk:"Создать образ всего диска",opCaptureP2v:"Преобразовать физический диск в QCOW2 (P2V)",opExportP2v:"Экспортировать P2V QCOW2 из S3",opRecoveryIso:"Создать автономный ISO восстановления",opCapturePartition:"Создать образ раздела",opCaptureVolume:"Создать образ логического тома",opRestoreDisk:"Восстановить весь диск",opRestorePartition:"Восстановить раздел",opRestoreVolume:"Восстановить логический том",opCloneDisk:"Клонировать диск на диск",opClonePartition:"Клонировать раздел на раздел",
    availableImages:"Доступные образы",imageRepository:"Хранилище образов",extractPartition:"Извлечь раздел из образа всего диска",createRemoteJob:"Создать удалённое задание развёртывания",deploymentJournals:"Журналы развёртывания",remoteImageRepositories:"Удалённые хранилища образов",localOperationHistory:"Локальная история операций"
  },
  ar: {
    tabImages:"مستودع الصور",tabRemoteJobs:"المهام البعيدة",tabHistory:"سجل النشر",tabRepositories:"المستودعات البعيدة",tabOperationLog:"سجل العمليات",tabNetwork:"الشبكة (الخادم / العميل)",
    opCaptureDisk:"إنشاء صورة للقرص بالكامل",opCaptureP2v:"تحويل قرص فعلي إلى QCOW2 (P2V)",opExportP2v:"تصدير P2V QCOW2 من S3",opRecoveryIso:"إنشاء ISO استرداد مستقل",opCapturePartition:"إنشاء صورة قسم",opCaptureVolume:"إنشاء صورة وحدة تخزين منطقية",opRestoreDisk:"استعادة القرص بالكامل",opRestorePartition:"استعادة قسم",opRestoreVolume:"استعادة وحدة تخزين منطقية",opCloneDisk:"استنساخ قرص إلى قرص",opClonePartition:"استنساخ قسم إلى قسم",
    availableImages:"الصور المتاحة",imageRepository:"مستودع الصور",extractPartition:"استخراج قسم من صورة قرص كامل",createRemoteJob:"إنشاء مهمة نشر بعيدة",deploymentJournals:"سجلات النشر",remoteImageRepositories:"مستودعات الصور البعيدة",localOperationHistory:"سجل العمليات المحلي"
  },
  tr: {
    tabImages:"Görüntü deposu",tabRemoteJobs:"Uzak işler",tabHistory:"Dağıtım geçmişi",tabRepositories:"Uzak depolar",tabOperationLog:"İşlem günlüğü",tabNetwork:"Ağ (Sunucu / İstemci)",
    opCaptureDisk:"Tam disk görüntüsü oluştur",opCaptureP2v:"Fiziksel diski QCOW2'ye dönüştür (P2V)",opExportP2v:"S3'ten P2V QCOW2 dışa aktar",opRecoveryIso:"Bağımsız kurtarma ISO'su oluştur",opCapturePartition:"Bölüm görüntüsü oluştur",opCaptureVolume:"Mantıksal birim görüntüsü oluştur",opRestoreDisk:"Tam diski geri yükle",opRestorePartition:"Bölümü geri yükle",opRestoreVolume:"Mantıksal birimi geri yükle",opCloneDisk:"Diski diske klonla",opClonePartition:"Bölümü bölüme klonla",
    availableImages:"Kullanılabilir görüntüler",imageRepository:"Görüntü deposu",extractPartition:"Tam disk görüntüsünden bölüm çıkar",createRemoteJob:"Uzak dağıtım işi oluştur",deploymentJournals:"Dağıtım günlükleri",remoteImageRepositories:"Uzak görüntü depoları",localOperationHistory:"Yerel işlem geçmişi"
  }
};



const CORE_TRANSLATION_COMPLETION = {
  es: {
    storageSafety:"Feclora vuelve a comprobar la identidad del dispositivo, los montajes, el uso del sistema, la geometría y la integridad de la imagen justo antes de escribir.",
    terminalHelp:"Para configurar el sistema, diagnosticar la red y realizar tareas avanzadas, utiliza la página Terminal de Cockpit. No la uses para eludir las comprobaciones de seguridad de Feclora.",
    footer:"Todas las operaciones de almacenamiento utilizan los motores Python compartidos de Feclora. Cockpit es la interfaz principal.",
    chooseLayout:"Elige la distribución física del teclado independientemente del idioma de la interfaz. Esta opción actualiza el mapa persistente de la consola virtual Linux y la consola de texto activa.",
    consoleOnly:"La implementación actual configura la consola virtual de Linux. La sesión gráfica Cage/Wayland todavía necesita una integración XKB independiente; este control aún no modifica esa sesión.",
    operationLabels:"Etiquetas de las operaciones"
  },
  ca: { operationLabels:"Etiquetes de les operacions" },
  gl: {
    manifests:"Imaxes locais con manifesto",recordedJobs:"Tarefas rexistradas e estado de recuperación",loading:"Cargando Feclora",
    chooseOperation:"Escolle unha operación, revisa os dispositivos e confirma expresamente cada destino destrutivo.",
    safety:"Modelo de seguridade",storageSafety:"Feclora volve comprobar a identidade do dispositivo, as montaxes, o uso do sistema, a xeometría e a integridade da imaxe xusto antes de escribir.",
    generateSecurity:"Xera unha CA local de Feclora e unha identidade age opcional. As claves privadas permanecen neste equipo.",
    capability:"Capacidade",ready:"Preparado",notInitialized:"Non inicializado",
    terminalHelp:"Para configurar o sistema, diagnosticar a rede e realizar tarefas avanzadas, utiliza a páxina Terminal de Cockpit. Non a empregues para evitar as comprobacións de seguridade de Feclora.",
    footer:"Todas as operacións de almacenamento utilizan os motores Python compartidos de Feclora. Cockpit é a interface principal.",
    chooseLayout:"Escolle a distribución física do teclado independentemente do idioma da interface. Esta opción actualiza o mapa persistente da consola virtual Linux e a consola de texto activa.",
    currentKeymap:"Mapa de teclado Linux actual",scope:"Ámbito",
    consoleOnly:"A implementación actual configura a consola virtual de Linux. A sesión gráfica Cage/Wayland aínda precisa unha integración XKB independente; este control non modifica esa sesión.",
    operationLabels:"Etiquetas das operacións",storageDevices:"Dispositivos de bloque e particións",model:"Modelo",filesystem:"Sistema de ficheiros",mounts:"Puntos de montaxe"
  },
  eu: {
    manifests:"Manifestua duten irudi lokalak",recordedJobs:"Erregistratutako lanak eta berreskuratze-egoera",loading:"Feclora kargatzen",
    chooseOperation:"Aukeratu eragiketa bat, berrikusi hautatutako gailuak eta berretsi berariaz suntsitzailea den helburu bakoitza.",
    safety:"Segurtasun-eredua",storageSafety:"Feclorak gailuaren identitatea, muntaketak, sistemaren erabilera, geometria eta irudiaren osotasuna berriro egiaztatzen ditu idatzi aurretik.",
    generateSecurity:"Sortu Fecloraren CA lokala eta aukerako age identitatea. Gako pribatuak makina honetan geratzen dira.",
    capability:"Gaitasuna",ready:"Prest",notInitialized:"Hasieratu gabe",
    terminalHelp:"Sistema konfiguratzeko, sarea diagnostikatzeko eta administrazio aurreratua egiteko, erabili Cockpit-eko Terminal orria. Ez erabili Fecloraren biltegiratze-segurtasuneko egiaztapenak saihesteko.",
    footer:"Biltegiratze-eragiketa guztiek Fecloraren Python motor partekatuak erabiltzen dituzte. Cockpit da operadorearen interfaze nagusia.",
    chooseLayout:"Aukeratu teklatu fisikoaren diseinua interfazearen hizkuntzatik bereizita. Ezarpen honek Linux kontsola birtualaren mapa iraunkorra eta testu-kontsola aktiboa eguneratzen ditu.",
    currentKeymap:"Uneko Linux teklatu-mapa",scope:"Esparrua",
    consoleOnly:"Uneko inplementazioak Linux kontsola birtuala konfiguratzen du. Cage/Wayland saio grafikoak XKB integrazio bereizia behar du oraindik; kontrol honek ez du saio hori aldatzen.",
    operationLabels:"Eragiketen etiketak",storageDevices:"Bloke-gailuak eta partizioak",model:"Modeloa",filesystem:"Fitxategi-sistema",mounts:"Muntatze-puntuak"
  },
  pt: {
    manifests:"Imagens locais com manifesto",recordedJobs:"Tarefas registadas e estado de recuperação",loading:"A carregar o Feclora",
    chooseOperation:"Escolha uma operação, reveja os dispositivos selecionados e confirme expressamente cada destino destrutivo.",
    safety:"Modelo de segurança",storageSafety:"O Feclora volta a verificar a identidade do dispositivo, as montagens, a utilização pelo sistema, a geometria e a integridade da imagem imediatamente antes de escrever.",
    generateSecurity:"Gere uma CA local do Feclora e uma identidade age opcional. As chaves privadas permanecem nesta máquina.",
    capability:"Capacidade",ready:"Pronto",notInitialized:"Não inicializado",
    terminalHelp:"Para configurar o sistema, diagnosticar a rede e administrar funcionalidades avançadas, utilize a página Terminal do Cockpit. Não a utilize para contornar as verificações de segurança do Feclora.",
    footer:"Todas as operações de armazenamento utilizam os motores Python partilhados do Feclora. O Cockpit é a interface principal do operador.",
    chooseLayout:"Escolha a disposição física do teclado independentemente do idioma da interface. Esta definição atualiza o mapa persistente da consola virtual Linux e a consola de texto ativa.",
    currentKeymap:"Mapa de teclado Linux atual",scope:"Âmbito",
    consoleOnly:"A implementação atual configura a consola virtual Linux. A sessão gráfica Cage/Wayland ainda necessita de integração XKB própria; este controlo ainda não altera essa sessão.",
    operationLabels:"Etiquetas das operações",storageDevices:"Dispositivos de bloco e partições",model:"Modelo",filesystem:"Sistema de ficheiros",mounts:"Pontos de montagem"
  },
  fr: {
    manifests:"Images locales avec manifeste",recordedJobs:"Tâches enregistrées et état de récupération",loading:"Chargement de Feclora",
    chooseOperation:"Choisissez une opération, vérifiez les périphériques sélectionnés et confirmez explicitement chaque destination destructive.",
    safety:"Modèle de sécurité",storageSafety:"Feclora revérifie l’identité du périphérique, les montages, l’utilisation par le système, la géométrie et l’intégrité de l’image juste avant toute écriture.",
    generateSecurity:"Générez une autorité de certification locale Feclora et une identité age facultative. Les clés privées restent sur cette machine.",
    capability:"Capacité",ready:"Prêt",notInitialized:"Non initialisé",
    terminalHelp:"Pour configurer le système, diagnostiquer le réseau et effectuer l’administration avancée, utilisez la page Terminal de Cockpit. Ne l’utilisez pas pour contourner les contrôles de sécurité de Feclora.",
    footer:"Toutes les opérations de stockage utilisent les moteurs Python partagés de Feclora. Cockpit est l’interface opérateur principale.",
    chooseLayout:"Choisissez la disposition physique du clavier indépendamment de la langue de l’interface. Ce réglage met à jour la carte persistante de la console virtuelle Linux et la console texte active.",
    currentKeymap:"Disposition Linux actuelle",scope:"Portée",
    consoleOnly:"L’implémentation actuelle configure la console virtuelle Linux. La session graphique Cage/Wayland nécessite encore une intégration XKB distincte ; ce contrôle ne modifie pas cette session.",
    operationLabels:"Libellés des opérations",storageDevices:"Périphériques bloc et partitions",model:"Modèle",filesystem:"Système de fichiers",mounts:"Points de montage"
  },
  de: {
    manifests:"Lokale Images mit Manifest",recordedJobs:"Aufgezeichnete Aufträge und Wiederherstellungsstatus",loading:"Feclora wird geladen",
    chooseOperation:"Wählen Sie einen Vorgang, prüfen Sie die ausgewählten Geräte und bestätigen Sie jedes destruktive Ziel ausdrücklich.",
    safety:"Sicherheitsmodell",storageSafety:"Feclora prüft unmittelbar vor dem Schreiben erneut Geräteidentität, Einbindungen, Systemnutzung, Geometrie und Image-Integrität.",
    generateSecurity:"Erstellen Sie eine lokale Feclora-CA und optional eine age-Identität. Private Schlüssel verbleiben auf diesem Rechner.",
    capability:"Funktion",ready:"Bereit",notInitialized:"Nicht initialisiert",
    terminalHelp:"Verwenden Sie für Systemeinrichtung, Netzwerkdiagnose und erweiterte Administration die Terminal-Seite von Cockpit. Umgehen Sie damit nicht die Speichersicherheitsprüfungen von Feclora.",
    footer:"Alle Speicheroperationen verwenden die gemeinsamen Python-Engines von Feclora. Cockpit ist die primäre Bedienoberfläche.",
    chooseLayout:"Wählen Sie das physische Tastaturlayout unabhängig von der Oberflächensprache. Diese Einstellung aktualisiert das persistente Layout der virtuellen Linux-Konsole und die aktive Textkonsole.",
    currentKeymap:"Aktuelles Linux-Tastaturlayout",scope:"Geltungsbereich",
    consoleOnly:"Die aktuelle Implementierung konfiguriert die virtuelle Linux-Konsole. Für die grafische Cage/Wayland-Sitzung ist weiterhin eine separate XKB-Integration erforderlich; diese Einstellung ändert jene Sitzung noch nicht.",
    operationLabels:"Vorgangsbezeichnungen",storageDevices:"Blockgeräte und Partitionen",model:"Modell",filesystem:"Dateisystem",mounts:"Einhängepunkte"
  },
  it: {
    manifests:"Immagini locali con manifest",recordedJobs:"Operazioni registrate e stato di ripristino",loading:"Caricamento di Feclora",
    chooseOperation:"Scegli un'operazione, controlla i dispositivi selezionati e conferma esplicitamente ogni destinazione distruttiva.",
    safety:"Modello di sicurezza",storageSafety:"Feclora ricontrolla identità del dispositivo, montaggi, utilizzo da parte del sistema, geometria e integrità dell'immagine subito prima della scrittura.",
    generateSecurity:"Genera una CA locale Feclora e un'identità age facoltativa. Le chiavi private restano su questa macchina.",
    capability:"Funzionalità",ready:"Pronto",notInitialized:"Non inizializzato",
    terminalHelp:"Per configurazione del sistema, diagnostica di rete e amministrazione avanzata, usa la pagina Terminale di Cockpit. Non usarla per aggirare i controlli di sicurezza di Feclora.",
    footer:"Tutte le operazioni di archiviazione usano i motori Python condivisi di Feclora. Cockpit è l'interfaccia principale per l'operatore.",
    chooseLayout:"Scegli il layout fisico della tastiera indipendentemente dalla lingua dell'interfaccia. Questa impostazione aggiorna la mappa persistente della console virtuale Linux e la console testuale attiva.",
    currentKeymap:"Mappa tastiera Linux corrente",scope:"Ambito",
    consoleOnly:"L'implementazione attuale configura la console virtuale Linux. La sessione grafica Cage/Wayland richiede ancora un'integrazione XKB separata; questo controllo non modifica ancora quella sessione.",
    operationLabels:"Etichette delle operazioni",storageDevices:"Dispositivi a blocchi e partizioni",model:"Modello",filesystem:"File system",mounts:"Punti di montaggio"
  },
  zh: {
    manifests:"带清单的本地映像",recordedJobs:"已记录任务和恢复状态",loading:"正在加载 Feclora",
    chooseOperation:"选择操作，检查所选设备，并明确确认每个具有破坏性的目标。",
    safety:"安全模型",storageSafety:"Feclora 会在写入前立即重新检查设备身份、挂载状态、系统占用、几何参数和映像完整性。",
    generateSecurity:"生成本地 Feclora CA 和可选的 age 身份。私钥保留在此计算机上。",
    capability:"功能",ready:"就绪",notInitialized:"尚未初始化",
    terminalHelp:"如需系统设置、网络诊断和高级管理，请使用 Cockpit 的终端页面。不要利用终端绕过 Feclora 的存储安全检查。",
    footer:"所有存储操作均使用 Feclora 共享的 Python 引擎。Cockpit 是主要操作界面。",
    chooseLayout:"独立于界面语言选择物理键盘布局。此设置会更新持久化的 Linux 虚拟控制台键盘映射和当前文本控制台。",
    currentKeymap:"当前 Linux 键盘映射",scope:"范围",
    consoleOnly:"当前实现配置 Linux 虚拟控制台。Cage/Wayland 图形会话仍需单独的 XKB 集成；此控件目前不会更改该会话。",
    operationLabels:"操作标签",storageDevices:"块设备和分区",model:"型号",filesystem:"文件系统",mounts:"挂载点"
  },
  ja: {
    manifests:"マニフェスト付きローカルイメージ",recordedJobs:"記録済みジョブと復旧状態",loading:"Feclora を読み込み中",
    chooseOperation:"操作を選択し、選択したデバイスを確認して、破壊的な対象をそれぞれ明示的に承認してください。",
    safety:"安全モデル",storageSafety:"Feclora は書き込み直前にデバイス識別情報、マウント状態、システム使用状況、ジオメトリ、イメージ整合性を再確認します。",
    generateSecurity:"ローカル Feclora CA と任意の age ID を生成します。秘密鍵はこのマシン内に保持されます。",
    capability:"機能",ready:"準備完了",notInitialized:"未初期化",
    terminalHelp:"システム設定、ネットワーク診断、高度な管理には Cockpit の Terminal ページを使用してください。Feclora のストレージ安全確認を回避するために使用しないでください。",
    footer:"すべてのストレージ操作は Feclora の共有 Python エンジンを使用します。Cockpit が主な操作画面です。",
    chooseLayout:"インターフェース言語とは独立して物理キーボード配列を選択します。この設定は Linux 仮想コンソールの永続キーマップとアクティブなテキストコンソールを更新します。",
    currentKeymap:"現在の Linux キーマップ",scope:"適用範囲",
    consoleOnly:"現在の実装は Linux 仮想コンソールを設定します。Cage/Wayland グラフィカルセッションには別途 XKB 統合が必要であり、この設定はまだそのセッションを変更しません。",
    operationLabels:"操作ラベル",storageDevices:"ブロックデバイスとパーティション",model:"モデル",filesystem:"ファイルシステム",mounts:"マウントポイント"
  },
  ru: {
    manifests:"Локальные образы с манифестом",recordedJobs:"Записанные задания и состояние восстановления",loading:"Загрузка Feclora",
    chooseOperation:"Выберите операцию, проверьте выбранные устройства и явно подтвердите каждую цель с разрушительными последствиями.",
    safety:"Модель безопасности",storageSafety:"Непосредственно перед записью Feclora повторно проверяет идентификатор устройства, точки монтирования, использование системой, геометрию и целостность образа.",
    generateSecurity:"Создайте локальный центр сертификации Feclora и необязательную идентичность age. Закрытые ключи остаются на этом компьютере.",
    capability:"Возможность",ready:"Готово",notInitialized:"Не инициализировано",
    terminalHelp:"Для настройки системы, диагностики сети и расширенного администрирования используйте страницу Terminal в Cockpit. Не обходите через неё проверки безопасности хранилища Feclora.",
    footer:"Все операции хранения используют общие движки Python Feclora. Cockpit — основной интерфейс оператора.",
    chooseLayout:"Выберите физическую раскладку клавиатуры независимо от языка интерфейса. Настройка обновляет постоянную раскладку виртуальной консоли Linux и активную текстовую консоль.",
    currentKeymap:"Текущая раскладка Linux",scope:"Область действия",
    consoleOnly:"Текущая реализация настраивает виртуальную консоль Linux. Для графического сеанса Cage/Wayland по-прежнему требуется отдельная интеграция XKB; этот параметр пока не меняет такой сеанс.",
    operationLabels:"Названия операций",storageDevices:"Блочные устройства и разделы",model:"Модель",filesystem:"Файловая система",mounts:"Точки монтирования"
  },
  ar: {
    manifests:"صور محلية مدعومة ببيان",recordedJobs:"المهام المسجلة وحالة الاسترداد",loading:"جارٍ تحميل Feclora",
    chooseOperation:"اختر عملية، وراجع الأجهزة المحددة، وأكد صراحةً كل وجهة تتضمن إجراءً مدمراً.",
    safety:"نموذج الأمان",storageSafety:"يعيد Feclora التحقق من هوية الجهاز وحالات التحميل واستخدام النظام والهندسة وسلامة الصورة مباشرةً قبل الكتابة.",
    generateSecurity:"أنشئ سلطة شهادات محلية لـ Feclora وهوية age اختيارية. تبقى المفاتيح الخاصة على هذا الجهاز.",
    capability:"الإمكانات",ready:"جاهز",notInitialized:"لم تتم التهيئة",
    terminalHelp:"لإعداد النظام وتشخيص الشبكة والإدارة المتقدمة، استخدم صفحة Terminal في Cockpit. لا تستخدمها لتجاوز فحوصات أمان التخزين في Feclora.",
    footer:"تستخدم جميع عمليات التخزين محركات Python المشتركة في Feclora. Cockpit هي واجهة التشغيل الأساسية.",
    chooseLayout:"اختر تخطيط لوحة المفاتيح الفعلي بشكل مستقل عن لغة الواجهة. يحدّث هذا الإعداد خريطة مفاتيح وحدة تحكم Linux الافتراضية الدائمة ووحدة النص النشطة.",
    currentKeymap:"تخطيط مفاتيح Linux الحالي",scope:"النطاق",
    consoleOnly:"يضبط التنفيذ الحالي وحدة تحكم Linux الافتراضية. لا تزال جلسة Cage/Wayland الرسومية بحاجة إلى تكامل XKB منفصل؛ ولا يغيّر هذا الخيار تلك الجلسة حالياً.",
    operationLabels:"تسميات العمليات",storageDevices:"أجهزة الكتل والأقسام",model:"الطراز",filesystem:"نظام الملفات",mounts:"نقاط التحميل"
  },
  tr: {
    manifests:"Manifest destekli yerel görüntüler",recordedJobs:"Kaydedilen işler ve kurtarma durumu",loading:"Feclora yükleniyor",
    chooseOperation:"Bir işlem seçin, seçili aygıtları gözden geçirin ve yıkıcı hedeflerin her birini açıkça onaylayın.",
    safety:"Güvenlik modeli",storageSafety:"Feclora, yazmadan hemen önce aygıt kimliğini, bağlama durumlarını, sistem kullanımını, geometrisini ve görüntü bütünlüğünü yeniden denetler.",
    generateSecurity:"Yerel bir Feclora CA'sı ve isteğe bağlı age kimliği oluşturun. Özel anahtarlar bu makinede kalır.",
    capability:"Yetenek",ready:"Hazır",notInitialized:"Başlatılmadı",
    terminalHelp:"Sistem kurulumu, ağ tanılama ve gelişmiş yönetim için Cockpit Terminal sayfasını kullanın. Feclora depolama güvenliği denetimlerini atlamak için terminali kullanmayın.",
    footer:"Tüm depolama işlemleri Feclora'nın paylaşılan Python motorlarını kullanır. Cockpit birincil operatör arayüzüdür.",
    chooseLayout:"Fiziksel klavye düzenini arayüz dilinden bağımsız seçin. Bu ayar kalıcı Linux sanal konsol tuş haritasını ve etkin metin konsolunu günceller.",
    currentKeymap:"Geçerli Linux tuş haritası",scope:"Kapsam",
    consoleOnly:"Geçerli uygulama Linux sanal konsolunu yapılandırır. Cage/Wayland grafik oturumu için ayrıca XKB tümleştirmesi gerekir; bu denetim henüz o oturumu değiştirmez.",
    operationLabels:"İşlem etiketleri",storageDevices:"Blok aygıtları ve bölümler",model:"Model",filesystem:"Dosya sistemi",mounts:"Bağlama noktaları"
  }
};

const APP_UI_TEXT = {
  es: {
    "Compression":"Compresión","Image security":"Seguridad de la imagen","Image encryption passphrase":"Contraseña de cifrado de imagen","Encrypt artifacts with age":"Cifrar artefactos con age","Use a symmetric passphrase instead of recipient keys":"Usar una contraseña simétrica en lugar de claves de destinatario","Select an image…":"Selecciona una imagen…","Select a destination…":"Selecciona un destino…","Select a source device…":"Selecciona un dispositivo de origen…","Select source…":"Seleccionar origen…","Select destination…":"Seleccionar destino…","Whole disk":"Disco completo","Logical volume":"Volumen lógico","Partition":"Partición","Authenticated unicast":"Unidifusión autenticada","Do nothing — leave Client running":"No hacer nada: dejar el cliente encendido","Reboot Client after verified write":"Reiniciar el cliente tras verificar la escritura","Shut down Client after verified write":"Apagar el cliente tras verificar la escritura","Job ID":"ID del trabajo","Target":"Destino","Transport":"Transporte","State":"Estado","Recovery":"Recuperación","Events":"Eventos","Service and execution":"Servicio y ejecución","Review required · no auto-resume":"Revisión necesaria · sin reanudación automática","Close for audit":"Cerrar tras revisión","Authorize and execute":"Autorizar y ejecutar","Cancel before arm":"Cancelar antes de autorizar","Stop service":"Detener servicio","No deployment jobs recorded.":"No hay trabajos de despliegue registrados.","No local operations recorded.":"No hay operaciones locales registradas.","Read-only":"Solo lectura","Read/write":"Lectura y escritura","Test connection":"Probar conexión","Mount":"Montar","Unmount":"Desmontar","Edit":"Editar","Remove":"Eliminar","No S3 object repositories configured.":"No hay repositorios de objetos S3 configurados.","Configured repositories":"Repositorios configurados","Remote health unknown":"Estado remoto desconocido"
  },
  ca: {
    "Compression":"Compressió","Image security":"Seguretat de la imatge","Image encryption passphrase":"Contrasenya de xifratge de la imatge","Encrypt artifacts with age":"Xifra els artefactes amb age","Use a symmetric passphrase instead of recipient keys":"Fes servir una contrasenya simètrica en lloc de claus de destinataris","Select an image…":"Selecciona una imatge…","Select a destination…":"Selecciona una destinació…","Select a source device…":"Selecciona un dispositiu d'origen…","Select source…":"Selecciona l'origen…","Select destination…":"Selecciona la destinació…","Whole disk":"Disc sencer","Logical volume":"Volum lògic","Partition":"Partició","Authenticated unicast":"Unidifusió autenticada","Do nothing — leave Client running":"No facis res: deixa el Client en funcionament","Reboot Client after verified write":"Reinicia el Client després de verificar l'escriptura","Shut down Client after verified write":"Apaga el Client després de verificar l'escriptura","Job ID":"ID de la tasca","Target":"Destinació","Transport":"Transport","State":"Estat","Recovery":"Recuperació","Events":"Esdeveniments","Service and execution":"Servei i execució","Review required · no auto-resume":"Cal revisió · sense represa automàtica","Close for audit":"Tanca després de revisar","Authorize and execute":"Autoritza i executa","Cancel before arm":"Cancel·la abans d'autoritzar","Stop service":"Atura el servei","No deployment jobs recorded.":"No hi ha tasques de desplegament registrades.","No local operations recorded.":"No hi ha operacions locals registrades.","Read-only":"Només lectura","Read/write":"Lectura i escriptura","Test connection":"Prova la connexió","Mount":"Munta","Unmount":"Desmunta","Edit":"Edita","Remove":"Elimina","No S3 object repositories configured.":"No hi ha repositoris d'objectes S3 configurats.","Configured repositories":"Repositoris configurats","Remote health unknown":"Estat remot desconegut"
  },
  gl: {
    "Compression":"Compresión","Image security":"Seguridade da imaxe","Image encryption passphrase":"Contrasinal de cifrado da imaxe","Encrypt artifacts with age":"Cifrar artefactos con age","Use a symmetric passphrase instead of recipient keys":"Usar un contrasinal simétrico en lugar de claves destinatarias","Select an image…":"Selecciona unha imaxe…","Select a destination…":"Selecciona un destino…","Select a source device…":"Selecciona un dispositivo de orixe…","Select source…":"Seleccionar orixe…","Select destination…":"Seleccionar destino…","Whole disk":"Disco completo","Logical volume":"Volume lóxico","Partition":"Partición","Authenticated unicast":"Unicast autenticado","Do nothing — leave Client running":"Non facer nada: deixar o cliente en execución","Reboot Client after verified write":"Reiniciar o cliente tras verificar a escritura","Shut down Client after verified write":"Apagar o cliente tras verificar a escritura","Job ID":"ID da tarefa","Target":"Destino","Transport":"Transporte","State":"Estado","Recovery":"Recuperación","Events":"Eventos","Service and execution":"Servizo e execución","Review required · no auto-resume":"Cómpre revisar · sen reanudación automática","Close for audit":"Pechar tras revisar","Authorize and execute":"Autorizar e executar","Cancel before arm":"Cancelar antes de autorizar","Stop service":"Deter o servizo","No deployment jobs recorded.":"Non hai tarefas de despregamento rexistradas.","No local operations recorded.":"Non hai operacións locais rexistradas.","Read-only":"Só lectura","Read/write":"Lectura e escritura","Test connection":"Probar conexión","Mount":"Montar","Unmount":"Desmontar","Edit":"Editar","Remove":"Eliminar","No S3 object repositories configured.":"Non hai repositorios de obxectos S3 configurados.","Configured repositories":"Repositorios configurados","Remote health unknown":"Estado remoto descoñecido"
  },
  eu: {
    "Compression":"Konpresioa","Image security":"Irudiaren segurtasuna","Image encryption passphrase":"Irudia enkriptatzeko pasahitza","Encrypt artifacts with age":"Enkriptatu artefaktuak age erabiliz","Use a symmetric passphrase instead of recipient keys":"Erabili pasahitz simetrikoa hartzaileen gakoen ordez","Select an image…":"Hautatu irudi bat…","Select a destination…":"Hautatu helburu bat…","Select a source device…":"Hautatu jatorrizko gailu bat…","Select source…":"Hautatu jatorria…","Select destination…":"Hautatu helburua…","Whole disk":"Disko osoa","Logical volume":"Bolumen logikoa","Partition":"Partizioa","Authenticated unicast":"Unicast autentifikatua","Do nothing — leave Client running":"Ez egin ezer: utzi Bezeroa martxan","Reboot Client after verified write":"Berrabiarazi Bezeroa idazketa egiaztatu ondoren","Shut down Client after verified write":"Itzali Bezeroa idazketa egiaztatu ondoren","Job ID":"Lanaren IDa","Target":"Helburua","Transport":"Garraioa","State":"Egoera","Recovery":"Berreskuratzea","Events":"Gertaerak","Service and execution":"Zerbitzua eta exekuzioa","Review required · no auto-resume":"Berrikuspena behar da · ez dago berrekite automatikoa","Close for audit":"Itxi berrikusi ondoren","Authorize and execute":"Baimendu eta exekutatu","Cancel before arm":"Utzi baimendu aurretik","Stop service":"Gelditu zerbitzua","No deployment jobs recorded.":"Ez dago inplementazio-lanik erregistratuta.","No local operations recorded.":"Ez dago eragiketa lokalik erregistratuta.","Read-only":"Irakurtzeko soilik","Read/write":"Irakurtzeko/idazteko","Test connection":"Probatu konexioa","Mount":"Muntatu","Unmount":"Desmuntatu","Edit":"Editatu","Remove":"Kendu","No S3 object repositories configured.":"Ez dago S3 objektu-biltegi konfiguraturik.","Configured repositories":"Konfiguratutako biltegiak","Remote health unknown":"Urruneko osasuna ezezaguna"
  },
  pt: {
    "Compression":"Compressão","Image security":"Segurança da imagem","Image encryption passphrase":"Frase-passe de encriptação da imagem","Encrypt artifacts with age":"Encriptar artefactos com age","Use a symmetric passphrase instead of recipient keys":"Usar uma frase-passe simétrica em vez de chaves de destinatário","Select an image…":"Selecione uma imagem…","Select a destination…":"Selecione um destino…","Select a source device…":"Selecione um dispositivo de origem…","Select source…":"Selecionar origem…","Select destination…":"Selecionar destino…","Whole disk":"Disco completo","Logical volume":"Volume lógico","Partition":"Partição","Authenticated unicast":"Unicast autenticado","Do nothing — leave Client running":"Não fazer nada — manter o Cliente em execução","Reboot Client after verified write":"Reiniciar o Cliente após verificar a escrita","Shut down Client after verified write":"Desligar o Cliente após verificar a escrita","Job ID":"ID da tarefa","Target":"Destino","Transport":"Transporte","State":"Estado","Recovery":"Recuperação","Events":"Eventos","Service and execution":"Serviço e execução","Review required · no auto-resume":"É necessária revisão · sem retoma automática","Close for audit":"Fechar após revisão","Authorize and execute":"Autorizar e executar","Cancel before arm":"Cancelar antes de autorizar","Stop service":"Parar serviço","No deployment jobs recorded.":"Não existem tarefas de implementação registadas.","No local operations recorded.":"Não existem operações locais registadas.","Read-only":"Só de leitura","Read/write":"Leitura/escrita","Test connection":"Testar ligação","Mount":"Montar","Unmount":"Desmontar","Edit":"Editar","Remove":"Remover","No S3 object repositories configured.":"Não existem repositórios de objetos S3 configurados.","Configured repositories":"Repositórios configurados","Remote health unknown":"Estado remoto desconhecido"
  },
  fr: {
    "Compression":"Compression","Image security":"Sécurité de l’image","Image encryption passphrase":"Phrase secrète de chiffrement de l’image","Encrypt artifacts with age":"Chiffrer les artefacts avec age","Use a symmetric passphrase instead of recipient keys":"Utiliser une phrase secrète symétrique plutôt que des clés de destinataire","Select an image…":"Sélectionner une image…","Select a destination…":"Sélectionner une destination…","Select a source device…":"Sélectionner un périphérique source…","Select source…":"Sélectionner la source…","Select destination…":"Sélectionner la destination…","Whole disk":"Disque entier","Logical volume":"Volume logique","Partition":"Partition","Authenticated unicast":"Unicast authentifié","Do nothing — leave Client running":"Ne rien faire — laisser le Client en marche","Reboot Client after verified write":"Redémarrer le Client après vérification de l’écriture","Shut down Client after verified write":"Éteindre le Client après vérification de l’écriture","Job ID":"ID de tâche","Target":"Cible","Transport":"Transport","State":"État","Recovery":"Récupération","Events":"Événements","Service and execution":"Service et exécution","Review required · no auto-resume":"Vérification requise · aucune reprise automatique","Close for audit":"Clore après vérification","Authorize and execute":"Autoriser et exécuter","Cancel before arm":"Annuler avant armement","Stop service":"Arrêter le service","No deployment jobs recorded.":"Aucun travail de déploiement enregistré.","No local operations recorded.":"Aucune opération locale enregistrée.","Read-only":"Lecture seule","Read/write":"Lecture/écriture","Test connection":"Tester la connexion","Mount":"Monter","Unmount":"Démonter","Edit":"Modifier","Remove":"Supprimer","No S3 object repositories configured.":"Aucun dépôt d’objets S3 configuré.","Configured repositories":"Dépôts configurés","Remote health unknown":"État distant inconnu"
  },
  de: {
    "Compression":"Komprimierung","Image security":"Image-Sicherheit","Image encryption passphrase":"Passphrase zur Image-Verschlüsselung","Encrypt artifacts with age":"Artefakte mit age verschlüsseln","Use a symmetric passphrase instead of recipient keys":"Symmetrische Passphrase statt Empfängerschlüsseln verwenden","Select an image…":"Image auswählen…","Select a destination…":"Ziel auswählen…","Select a source device…":"Quellgerät auswählen…","Select source…":"Quelle auswählen…","Select destination…":"Ziel auswählen…","Whole disk":"Gesamte Festplatte","Logical volume":"Logisches Volume","Partition":"Partition","Authenticated unicast":"Authentifiziertes Unicast","Do nothing — leave Client running":"Nichts tun — Client weiterlaufen lassen","Reboot Client after verified write":"Client nach verifiziertem Schreibvorgang neu starten","Shut down Client after verified write":"Client nach verifiziertem Schreibvorgang herunterfahren","Job ID":"Auftrags-ID","Target":"Ziel","Transport":"Transport","State":"Status","Recovery":"Wiederherstellung","Events":"Ereignisse","Service and execution":"Dienst und Ausführung","Review required · no auto-resume":"Prüfung erforderlich · keine automatische Fortsetzung","Close for audit":"Nach Prüfung schließen","Authorize and execute":"Autorisieren und ausführen","Cancel before arm":"Vor Freigabe abbrechen","Stop service":"Dienst stoppen","No deployment jobs recorded.":"Keine Deployment-Aufträge aufgezeichnet.","No local operations recorded.":"Keine lokalen Vorgänge aufgezeichnet.","Read-only":"Schreibgeschützt","Read/write":"Lesen/Schreiben","Test connection":"Verbindung testen","Mount":"Einhängen","Unmount":"Aushängen","Edit":"Bearbeiten","Remove":"Entfernen","No S3 object repositories configured.":"Keine S3-Objektrepositories konfiguriert.","Configured repositories":"Konfigurierte Repositories","Remote health unknown":"Remote-Zustand unbekannt"
  },
  it: {
    "Compression":"Compressione","Image security":"Sicurezza dell'immagine","Image encryption passphrase":"Passphrase di cifratura dell'immagine","Encrypt artifacts with age":"Cifra gli artefatti con age","Use a symmetric passphrase instead of recipient keys":"Usa una passphrase simmetrica invece delle chiavi dei destinatari","Select an image…":"Seleziona un'immagine…","Select a destination…":"Seleziona una destinazione…","Select a source device…":"Seleziona un dispositivo sorgente…","Select source…":"Seleziona sorgente…","Select destination…":"Seleziona destinazione…","Whole disk":"Disco intero","Logical volume":"Volume logico","Partition":"Partizione","Authenticated unicast":"Unicast autenticato","Do nothing — leave Client running":"Non fare nulla — lascia il Client in esecuzione","Reboot Client after verified write":"Riavvia il Client dopo la verifica della scrittura","Shut down Client after verified write":"Spegni il Client dopo la verifica della scrittura","Job ID":"ID operazione","Target":"Destinazione","Transport":"Trasporto","State":"Stato","Recovery":"Ripristino","Events":"Eventi","Service and execution":"Servizio ed esecuzione","Review required · no auto-resume":"Revisione richiesta · nessuna ripresa automatica","Close for audit":"Chiudi dopo la revisione","Authorize and execute":"Autorizza ed esegui","Cancel before arm":"Annulla prima dell'armamento","Stop service":"Arresta il servizio","No deployment jobs recorded.":"Nessuna attività di distribuzione registrata.","No local operations recorded.":"Nessuna operazione locale registrata.","Read-only":"Sola lettura","Read/write":"Lettura/scrittura","Test connection":"Verifica connessione","Mount":"Monta","Unmount":"Smonta","Edit":"Modifica","Remove":"Rimuovi","No S3 object repositories configured.":"Nessun repository di oggetti S3 configurato.","Configured repositories":"Repository configurati","Remote health unknown":"Stato remoto sconosciuto"
  },
  zh: {
    "Compression":"压缩","Image security":"映像安全","Image encryption passphrase":"映像加密口令","Encrypt artifacts with age":"使用 age 加密文件","Use a symmetric passphrase instead of recipient keys":"使用对称口令而不是接收者密钥","Select an image…":"选择映像…","Select a destination…":"选择目标…","Select a source device…":"选择源设备…","Select source…":"选择源…","Select destination…":"选择目标…","Whole disk":"整块磁盘","Logical volume":"逻辑卷","Partition":"分区","Authenticated unicast":"经过身份验证的单播","Do nothing — leave Client running":"不执行操作 — 保持客户端运行","Reboot Client after verified write":"写入验证后重启客户端","Shut down Client after verified write":"写入验证后关闭客户端","Job ID":"任务 ID","Target":"目标","Transport":"传输方式","State":"状态","Recovery":"恢复","Events":"事件","Service and execution":"服务与执行","Review required · no auto-resume":"需要检查 · 不会自动恢复","Close for audit":"检查后关闭","Authorize and execute":"授权并执行","Cancel before arm":"授权前取消","Stop service":"停止服务","No deployment jobs recorded.":"没有已记录的部署任务。","No local operations recorded.":"没有已记录的本地操作。","Read-only":"只读","Read/write":"读写","Test connection":"测试连接","Mount":"挂载","Unmount":"卸载","Edit":"编辑","Remove":"移除","No S3 object repositories configured.":"尚未配置 S3 对象存储库。","Configured repositories":"已配置的存储库","Remote health unknown":"远程健康状态未知"
  },
  ja: {
    "Compression":"圧縮","Image security":"イメージのセキュリティ","Image encryption passphrase":"イメージ暗号化パスフレーズ","Encrypt artifacts with age":"age で成果物を暗号化","Use a symmetric passphrase instead of recipient keys":"受信者キーの代わりに対称パスフレーズを使用","Select an image…":"イメージを選択…","Select a destination…":"宛先を選択…","Select a source device…":"ソースデバイスを選択…","Select source…":"ソースを選択…","Select destination…":"宛先を選択…","Whole disk":"ディスク全体","Logical volume":"論理ボリューム","Partition":"パーティション","Authenticated unicast":"認証済みユニキャスト","Do nothing — leave Client running":"何もしない — Client を稼働したままにする","Reboot Client after verified write":"書き込み検証後に Client を再起動","Shut down Client after verified write":"書き込み検証後に Client をシャットダウン","Job ID":"ジョブ ID","Target":"対象","Transport":"転送方式","State":"状態","Recovery":"復旧","Events":"イベント","Service and execution":"サービスと実行","Review required · no auto-resume":"確認が必要 · 自動再開なし","Close for audit":"確認後に終了","Authorize and execute":"承認して実行","Cancel before arm":"承認前にキャンセル","Stop service":"サービスを停止","No deployment jobs recorded.":"記録されたデプロイジョブはありません。","No local operations recorded.":"記録されたローカル操作はありません。","Read-only":"読み取り専用","Read/write":"読み書き","Test connection":"接続をテスト","Mount":"マウント","Unmount":"アンマウント","Edit":"編集","Remove":"削除","No S3 object repositories configured.":"S3 オブジェクトリポジトリは設定されていません。","Configured repositories":"設定済みリポジトリ","Remote health unknown":"リモートの状態は不明"
  },
  ru: {
    "Compression":"Сжатие","Image security":"Безопасность образа","Image encryption passphrase":"Парольная фраза шифрования образа","Encrypt artifacts with age":"Шифровать артефакты с помощью age","Use a symmetric passphrase instead of recipient keys":"Использовать симметричную парольную фразу вместо ключей получателей","Select an image…":"Выберите образ…","Select a destination…":"Выберите назначение…","Select a source device…":"Выберите исходное устройство…","Select source…":"Выбрать источник…","Select destination…":"Выбрать назначение…","Whole disk":"Весь диск","Logical volume":"Логический том","Partition":"Раздел","Authenticated unicast":"Аутентифицированный unicast","Do nothing — leave Client running":"Ничего не делать — оставить Client включённым","Reboot Client after verified write":"Перезагрузить Client после проверки записи","Shut down Client after verified write":"Выключить Client после проверки записи","Job ID":"ID задания","Target":"Цель","Transport":"Транспорт","State":"Состояние","Recovery":"Восстановление","Events":"События","Service and execution":"Служба и выполнение","Review required · no auto-resume":"Требуется проверка · автоматическое возобновление отключено","Close for audit":"Закрыть после проверки","Authorize and execute":"Разрешить и выполнить","Cancel before arm":"Отменить до запуска","Stop service":"Остановить службу","No deployment jobs recorded.":"Нет зарегистрированных заданий развёртывания.","No local operations recorded.":"Нет зарегистрированных локальных операций.","Read-only":"Только чтение","Read/write":"Чтение/запись","Test connection":"Проверить соединение","Mount":"Подключить","Unmount":"Отключить","Edit":"Изменить","Remove":"Удалить","No S3 object repositories configured.":"Репозитории объектов S3 не настроены.","Configured repositories":"Настроенные репозитории","Remote health unknown":"Состояние удалённого узла неизвестно"
  },
  ar: {
    "Compression":"الضغط","Image security":"أمان الصورة","Image encryption passphrase":"عبارة مرور تشفير الصورة","Encrypt artifacts with age":"تشفير الملفات باستخدام age","Use a symmetric passphrase instead of recipient keys":"استخدم عبارة مرور متماثلة بدلاً من مفاتيح المستلمين","Select an image…":"اختر صورة…","Select a destination…":"اختر وجهة…","Select a source device…":"اختر جهاز المصدر…","Select source…":"اختر المصدر…","Select destination…":"اختر الوجهة…","Whole disk":"القرص بالكامل","Logical volume":"وحدة تخزين منطقية","Partition":"قسم","Authenticated unicast":"إرسال أحادي موثّق","Do nothing — leave Client running":"لا تفعل شيئاً — اترك العميل قيد التشغيل","Reboot Client after verified write":"أعد تشغيل العميل بعد التحقق من الكتابة","Shut down Client after verified write":"أوقف تشغيل العميل بعد التحقق من الكتابة","Job ID":"معرّف المهمة","Target":"الهدف","Transport":"النقل","State":"الحالة","Recovery":"الاسترداد","Events":"الأحداث","Service and execution":"الخدمة والتنفيذ","Review required · no auto-resume":"تجب المراجعة · لا استئناف تلقائياً","Close for audit":"إغلاق بعد المراجعة","Authorize and execute":"تفويض وتنفيذ","Cancel before arm":"إلغاء قبل التسليح","Stop service":"إيقاف الخدمة","No deployment jobs recorded.":"لا توجد مهام نشر مسجلة.","No local operations recorded.":"لا توجد عمليات محلية مسجلة.","Read-only":"للقراءة فقط","Read/write":"قراءة وكتابة","Test connection":"اختبار الاتصال","Mount":"تحميل","Unmount":"إلغاء التحميل","Edit":"تعديل","Remove":"إزالة","No S3 object repositories configured.":"لم يتم إعداد مستودعات كائنات S3.","Configured repositories":"المستودعات المُعدة","Remote health unknown":"حالة النظام البعيد غير معروفة"
  },
  tr: {
    "Compression":"Sıkıştırma","Image security":"Görüntü güvenliği","Image encryption passphrase":"Görüntü şifreleme parolası","Encrypt artifacts with age":"Yapıtları age ile şifrele","Use a symmetric passphrase instead of recipient keys":"Alıcı anahtarları yerine simetrik parola kullan","Select an image…":"Bir görüntü seçin…","Select a destination…":"Bir hedef seçin…","Select a source device…":"Bir kaynak aygıt seçin…","Select source…":"Kaynak seç…","Select destination…":"Hedef seç…","Whole disk":"Tüm disk","Logical volume":"Mantıksal birim","Partition":"Bölüm","Authenticated unicast":"Kimliği doğrulanmış tekil yayın","Do nothing — leave Client running":"Hiçbir şey yapma — İstemciyi çalışır bırak","Reboot Client after verified write":"Yazma doğrulandıktan sonra İstemciyi yeniden başlat","Shut down Client after verified write":"Yazma doğrulandıktan sonra İstemciyi kapat","Job ID":"İş kimliği","Target":"Hedef","Transport":"Aktarım","State":"Durum","Recovery":"Kurtarma","Events":"Olaylar","Service and execution":"Hizmet ve yürütme","Review required · no auto-resume":"İnceleme gerekli · otomatik devam yok","Close for audit":"İncelemeden sonra kapat","Authorize and execute":"Yetkilendir ve yürüt","Cancel before arm":"Yetkilendirmeden önce iptal et","Stop service":"Hizmeti durdur","No deployment jobs recorded.":"Kaydedilmiş dağıtım işi yok.","No local operations recorded.":"Kaydedilmiş yerel işlem yok.","Read-only":"Salt okunur","Read/write":"Okuma/yazma","Test connection":"Bağlantıyı test et","Mount":"Bağla","Unmount":"Ayır","Edit":"Düzenle","Remove":"Kaldır","No S3 object repositories configured.":"Yapılandırılmış S3 nesne deposu yok.","Configured repositories":"Yapılandırılmış depolar","Remote health unknown":"Uzak sistem durumu bilinmiyor"
  }
};

const APP_FORM_LABELS = {
  es: {"Operation":"Operación","Image repository":"Repositorio de imágenes","Image identifier":"Identificador de imagen","Target":"Destino","Source":"Origen","Destination":"Destino","Typed confirmation":"Confirmación escrita","Repository ID":"ID del repositorio","Username":"Nombre de usuario","Credential type":"Tipo de credencial","Mount access":"Acceso de montaje","IPv4 address":"Dirección IPv4"},
  ca: {"Operation":"Operació","Image repository":"Repositori d'imatges","Image identifier":"Identificador de la imatge","Target":"Destinació","Source":"Origen","Destination":"Destinació","Typed confirmation":"Confirmació escrita","Repository ID":"ID del repositori","Username":"Nom d'usuari","Credential type":"Tipus de credencial","Mount access":"Accés al muntatge","IPv4 address":"Adreça IPv4"},
  gl: {"Operation":"Operación","Image repository":"Repositorio de imaxes","Image identifier":"Identificador da imaxe","Target":"Destino","Source":"Orixe","Destination":"Destino","Typed confirmation":"Confirmación escrita","Repository ID":"ID do repositorio","Username":"Nome de usuario","Credential type":"Tipo de credencial","Mount access":"Acceso á montaxe","IPv4 address":"Enderezo IPv4"},
  eu: {"Operation":"Eragiketa","Image repository":"Irudien biltegia","Image identifier":"Irudiaren identifikatzailea","Target":"Helburua","Source":"Iturria","Destination":"Helmuga","Typed confirmation":"Idatzizko berrespena","Repository ID":"Biltegiaren IDa","Username":"Erabiltzaile-izena","Credential type":"Kredentzial mota","Mount access":"Muntatze-sarbidea","IPv4 address":"IPv4 helbidea"},
  pt: {"Operation":"Operação","Image repository":"Repositório de imagens","Image identifier":"Identificador da imagem","Target":"Destino","Source":"Origem","Destination":"Destino","Typed confirmation":"Confirmação escrita","Repository ID":"ID do repositório","Username":"Nome de utilizador","Credential type":"Tipo de credencial","Mount access":"Acesso à montagem","IPv4 address":"Endereço IPv4"},
  fr: {"Operation":"Opération","Image repository":"Dépôt d’images","Image identifier":"Identifiant de l’image","Target":"Cible","Source":"Source","Destination":"Destination","Typed confirmation":"Confirmation saisie","Repository ID":"ID du dépôt","Username":"Nom d’utilisateur","Credential type":"Type d’identifiant","Mount access":"Accès au montage","IPv4 address":"Adresse IPv4"},
  de: {"Operation":"Vorgang","Image repository":"Image-Repository","Image identifier":"Image-Kennung","Target":"Ziel","Source":"Quelle","Destination":"Ziel","Typed confirmation":"Eingegebene Bestätigung","Repository ID":"Repository-ID","Username":"Benutzername","Credential type":"Anmeldedatentyp","Mount access":"Einbindungszugriff","IPv4 address":"IPv4-Adresse"},
  it: {"Operation":"Operazione","Image repository":"Repository delle immagini","Image identifier":"Identificativo immagine","Target":"Destinazione","Source":"Origine","Destination":"Destinazione","Typed confirmation":"Conferma digitata","Repository ID":"ID repository","Username":"Nome utente","Credential type":"Tipo di credenziale","Mount access":"Accesso al montaggio","IPv4 address":"Indirizzo IPv4"},
  zh: {"Operation":"操作","Image repository":"映像存储库","Image identifier":"映像标识符","Target":"目标","Source":"源","Destination":"目标位置","Typed confirmation":"输入确认文本","Repository ID":"存储库 ID","Username":"用户名","Credential type":"凭据类型","Mount access":"挂载访问权限","IPv4 address":"IPv4 地址"},
  ja: {"Operation":"操作","Image repository":"イメージリポジトリ","Image identifier":"イメージ識別子","Target":"対象","Source":"ソース","Destination":"宛先","Typed confirmation":"確認文の入力","Repository ID":"リポジトリ ID","Username":"ユーザー名","Credential type":"認証情報の種類","Mount access":"マウントアクセス","IPv4 address":"IPv4 アドレス"},
  ru: {"Operation":"Операция","Image repository":"Репозиторий образов","Image identifier":"Идентификатор образа","Target":"Цель","Source":"Источник","Destination":"Назначение","Typed confirmation":"Введённое подтверждение","Repository ID":"ID репозитория","Username":"Имя пользователя","Credential type":"Тип учётных данных","Mount access":"Доступ к монтированию","IPv4 address":"Адрес IPv4"},
  ar: {"Operation":"العملية","Image repository":"مستودع الصور","Image identifier":"معرّف الصورة","Target":"الهدف","Source":"المصدر","Destination":"الوجهة","Typed confirmation":"التأكيد المكتوب","Repository ID":"معرّف المستودع","Username":"اسم المستخدم","Credential type":"نوع بيانات الاعتماد","Mount access":"صلاحية التحميل","IPv4 address":"عنوان IPv4"},
  tr: {"Operation":"İşlem","Image repository":"Görüntü deposu","Image identifier":"Görüntü tanımlayıcısı","Target":"Hedef","Source":"Kaynak","Destination":"Hedef","Typed confirmation":"Yazılı onay","Repository ID":"Depo kimliği","Username":"Kullanıcı adı","Credential type":"Kimlik bilgisi türü","Mount access":"Bağlama erişimi","IPv4 address":"IPv4 adresi"}
};

const APP_WORKFLOW_TEXT = {
  es: {"Verified S3 P2V export":"Exportación P2V de S3 verificada","S3 source repository":"Repositorio de origen S3","Committed P2V image":"Imagen P2V confirmada","Filesystem destination repository":"Repositorio de destino del sistema de archivos","Self-contained recovery media":"Medio de recuperación autónomo","Base Feclora Live ISO path":"Ruta de la ISO base de Feclora Live","Whole-disk image to embed":"Imagen de disco completo que se incluirá","Target disk WWN (recommended)":"WWN del disco de destino (recomendado)","Target disk serial (alternative or additional selector)":"Número de serie del disco de destino (selector alternativo o adicional)","Confirm ISO creation":"Confirmar creación de ISO","Typed build confirmation":"Confirmación escrita de la compilación","P2V output":"Resultado P2V"},
  ca: {"Verified S3 P2V export":"Exportació P2V de S3 verificada","S3 source repository":"Repositori d'origen S3","Committed P2V image":"Imatge P2V confirmada","Filesystem destination repository":"Repositori de destinació del sistema de fitxers","Self-contained recovery media":"Suport de recuperació autònom","Base Feclora Live ISO path":"Camí de la ISO base de Feclora Live","Whole-disk image to embed":"Imatge de disc sencer que s'hi inclourà","Target disk WWN (recommended)":"WWN del disc de destinació (recomanat)","Target disk serial (alternative or additional selector)":"Número de sèrie del disc de destinació (selector alternatiu o addicional)","Confirm ISO creation":"Confirma la creació de la ISO","Typed build confirmation":"Confirmació escrita de la construcció","P2V output":"Resultat P2V"},
  gl: {"Verified S3 P2V export":"Exportación P2V de S3 verificada","S3 source repository":"Repositorio de orixe S3","Committed P2V image":"Imaxe P2V confirmada","Filesystem destination repository":"Repositorio de destino do sistema de ficheiros","Self-contained recovery media":"Medio de recuperación autónomo","Base Feclora Live ISO path":"Ruta da ISO base de Feclora Live","Whole-disk image to embed":"Imaxe de disco completo que se incluirá","Target disk WWN (recommended)":"WWN do disco de destino (recomendado)","Target disk serial (alternative or additional selector)":"Número de serie do disco de destino (selector alternativo ou adicional)","Confirm ISO creation":"Confirmar a creación da ISO","Typed build confirmation":"Confirmación escrita da compilación","P2V output":"Resultado P2V"},
  eu: {"Verified S3 P2V export":"S3 P2V esportazio egiaztatua","S3 source repository":"S3 jatorrizko biltegia","Committed P2V image":"Berretsitako P2V irudia","Filesystem destination repository":"Fitxategi-sistemako helmuga-biltegia","Self-contained recovery media":"Berreskuratze-euskarri autonomoa","Base Feclora Live ISO path":"Feclora Live oinarrizko ISOaren bidea","Whole-disk image to embed":"Txertatu beharreko disko osoko irudia","Target disk WWN (recommended)":"Helburuko diskoaren WWN (gomendatua)","Target disk serial (alternative or additional selector)":"Helburuko diskoaren serie-zenbakia (hautazko ordezkoa edo osagarria)","Confirm ISO creation":"Berretsi ISOaren sorrera","Typed build confirmation":"Eraikuntzaren idatzizko berrespena","P2V output":"P2V irteera"},
  pt: {"Verified S3 P2V export":"Exportação P2V de S3 verificada","S3 source repository":"Repositório de origem S3","Committed P2V image":"Imagem P2V confirmada","Filesystem destination repository":"Repositório de destino do sistema de ficheiros","Self-contained recovery media":"Suporte de recuperação autónomo","Base Feclora Live ISO path":"Caminho da ISO base do Feclora Live","Whole-disk image to embed":"Imagem de disco completo a incluir","Target disk WWN (recommended)":"WWN do disco de destino (recomendado)","Target disk serial (alternative or additional selector)":"Número de série do disco de destino (seletor alternativo ou adicional)","Confirm ISO creation":"Confirmar criação da ISO","Typed build confirmation":"Confirmação escrita da compilação","P2V output":"Resultado P2V"},
  fr: {"Verified S3 P2V export":"Exportation P2V S3 vérifiée","S3 source repository":"Dépôt source S3","Committed P2V image":"Image P2V validée","Filesystem destination repository":"Dépôt de destination du système de fichiers","Self-contained recovery media":"Support de récupération autonome","Base Feclora Live ISO path":"Chemin de l’ISO Feclora Live de base","Whole-disk image to embed":"Image disque entière à intégrer","Target disk WWN (recommended)":"WWN du disque cible (recommandé)","Target disk serial (alternative or additional selector)":"Numéro de série du disque cible (sélecteur alternatif ou supplémentaire)","Confirm ISO creation":"Confirmer la création de l’ISO","Typed build confirmation":"Confirmation écrite de la compilation","P2V output":"Résultat P2V"},
  de: {"Verified S3 P2V export":"Verifizierter S3-P2V-Export","S3 source repository":"S3-Quell-Repository","Committed P2V image":"Festgeschriebenes P2V-Image","Filesystem destination repository":"Ziel-Repository des Dateisystems","Self-contained recovery media":"Eigenständiges Wiederherstellungsmedium","Base Feclora Live ISO path":"Pfad zur Feclora-Live-Basis-ISO","Whole-disk image to embed":"Einzubettendes vollständiges Festplatten-Image","Target disk WWN (recommended)":"WWN der Zielfestplatte (empfohlen)","Target disk serial (alternative or additional selector)":"Seriennummer der Zielfestplatte (alternativer oder zusätzlicher Selektor)","Confirm ISO creation":"ISO-Erstellung bestätigen","Typed build confirmation":"Eingegebene Build-Bestätigung","P2V output":"P2V-Ausgabe"},
  it: {"Verified S3 P2V export":"Esportazione P2V S3 verificata","S3 source repository":"Repository sorgente S3","Committed P2V image":"Immagine P2V confermata","Filesystem destination repository":"Repository di destinazione del filesystem","Self-contained recovery media":"Supporto di ripristino autonomo","Base Feclora Live ISO path":"Percorso ISO base di Feclora Live","Whole-disk image to embed":"Immagine dell'intero disco da incorporare","Target disk WWN (recommended)":"WWN del disco di destinazione (consigliato)","Target disk serial (alternative or additional selector)":"Numero di serie del disco di destinazione (selettore alternativo o aggiuntivo)","Confirm ISO creation":"Conferma creazione ISO","Typed build confirmation":"Conferma di compilazione digitata","P2V output":"Output P2V"},
  zh: {"Verified S3 P2V export":"已验证的 S3 P2V 导出","S3 source repository":"S3 源存储库","Committed P2V image":"已提交的 P2V 映像","Filesystem destination repository":"文件系统目标存储库","Self-contained recovery media":"独立恢复介质","Base Feclora Live ISO path":"Feclora Live 基础 ISO 路径","Whole-disk image to embed":"要嵌入的整盘映像","Target disk WWN (recommended)":"目标磁盘 WWN（推荐）","Target disk serial (alternative or additional selector)":"目标磁盘序列号（替代或附加标识）","Confirm ISO creation":"确认创建 ISO","Typed build confirmation":"输入构建确认文本","P2V output":"P2V 输出"},
  ja: {"Verified S3 P2V export":"検証済み S3 P2V エクスポート","S3 source repository":"S3 ソースリポジトリ","Committed P2V image":"確定済み P2V イメージ","Filesystem destination repository":"ファイルシステムの宛先リポジトリ","Self-contained recovery media":"スタンドアロン復旧メディア","Base Feclora Live ISO path":"Feclora Live ベース ISO のパス","Whole-disk image to embed":"埋め込むディスク全体のイメージ","Target disk WWN (recommended)":"ターゲットディスクの WWN（推奨）","Target disk serial (alternative or additional selector)":"ターゲットディスクのシリアル番号（代替または追加の識別子）","Confirm ISO creation":"ISO 作成の確認","Typed build confirmation":"ビルド確認文の入力","P2V output":"P2V 出力"},
  ru: {"Verified S3 P2V export":"Проверенный экспорт P2V из S3","S3 source repository":"Исходный репозиторий S3","Committed P2V image":"Зафиксированный образ P2V","Filesystem destination repository":"Целевой репозиторий файловой системы","Self-contained recovery media":"Автономный носитель восстановления","Base Feclora Live ISO path":"Путь к базовому ISO Feclora Live","Whole-disk image to embed":"Встраиваемый образ всего диска","Target disk WWN (recommended)":"WWN целевого диска (рекомендуется)","Target disk serial (alternative or additional selector)":"Серийный номер целевого диска (альтернативный или дополнительный идентификатор)","Confirm ISO creation":"Подтвердить создание ISO","Typed build confirmation":"Введённое подтверждение сборки","P2V output":"Результат P2V"},
  ar: {"Verified S3 P2V export":"تصدير P2V من S3 تم التحقق منه","S3 source repository":"مستودع مصدر S3","Committed P2V image":"صورة P2V معتمدة","Filesystem destination repository":"مستودع وجهة نظام الملفات","Self-contained recovery media":"وسيط استرداد مستقل","Base Feclora Live ISO path":"مسار ISO الأساسي لـ Feclora Live","Whole-disk image to embed":"صورة القرص بالكامل المراد تضمينها","Target disk WWN (recommended)":"WWN للقرص الهدف (موصى به)","Target disk serial (alternative or additional selector)":"الرقم التسلسلي للقرص الهدف (محدد بديل أو إضافي)","Confirm ISO creation":"تأكيد إنشاء ISO","Typed build confirmation":"تأكيد البناء المكتوب","P2V output":"مخرجات P2V"},
  tr: {"Verified S3 P2V export":"Doğrulanmış S3 P2V dışa aktarımı","S3 source repository":"S3 kaynak deposu","Committed P2V image":"Kaydedilmiş P2V görüntüsü","Filesystem destination repository":"Dosya sistemi hedef deposu","Self-contained recovery media":"Bağımsız kurtarma ortamı","Base Feclora Live ISO path":"Temel Feclora Live ISO yolu","Whole-disk image to embed":"Eklenecek tam disk görüntüsü","Target disk WWN (recommended)":"Hedef diskin WWN değeri (önerilir)","Target disk serial (alternative or additional selector)":"Hedef diskin seri numarası (alternatif veya ek tanımlayıcı)","Confirm ISO creation":"ISO oluşturmayı onayla","Typed build confirmation":"Yazılı derleme onayı","P2V output":"P2V çıktısı"}
};

const APP_SECTION_TEXT = {
  es: {"Server setup":"Configuración del servidor","Client jobs":"Tareas del cliente","Persisted remote jobs":"Tareas remotas guardadas","Encrypted repository credentials":"Credenciales cifradas del repositorio","S3 object repositories":"Repositorios de objetos S3","PXE network profile preflight":"Comprobación previa del perfil de red PXE","Remote job on this Client":"Tarea remota en este cliente","Authenticated Server job":"Tarea autenticada del servidor","Client service status":"Estado del servicio del cliente"},
  ca: {"Server setup":"Configuració del servidor","Client jobs":"Tasques del client","Persisted remote jobs":"Tasques remotes desades","Encrypted repository credentials":"Credencials xifrades del repositori","S3 object repositories":"Repositoris d'objectes S3","PXE network profile preflight":"Comprovació prèvia del perfil de xarxa PXE","Remote job on this Client":"Tasca remota en aquest client","Authenticated Server job":"Tasca autenticada del servidor","Client service status":"Estat del servei del client"},
  gl: {"Server setup":"Configuración do servidor","Client jobs":"Tarefas do cliente","Persisted remote jobs":"Tarefas remotas gardadas","Encrypted repository credentials":"Credenciais cifradas do repositorio","S3 object repositories":"Repositorios de obxectos S3","PXE network profile preflight":"Comprobación previa do perfil de rede PXE","Remote job on this Client":"Tarefa remota neste cliente","Authenticated Server job":"Tarefa autenticada do servidor","Client service status":"Estado do servizo do cliente"},
  eu: {"Server setup":"Zerbitzariaren konfigurazioa","Client jobs":"Bezeroaren lanak","Persisted remote jobs":"Gordetako urruneko lanak","Encrypted repository credentials":"Biltegiko kredentzial enkriptatuak","S3 object repositories":"S3 objektu-biltegiak","PXE network profile preflight":"PXE sare-profilaren aurre-egiaztapena","Remote job on this Client":"Bezero honetako urruneko lana","Authenticated Server job":"Zerbitzariaren lan autentifikatua","Client service status":"Bezero-zerbitzuaren egoera"},
  pt: {"Server setup":"Configuração do servidor","Client jobs":"Tarefas do cliente","Persisted remote jobs":"Tarefas remotas guardadas","Encrypted repository credentials":"Credenciais encriptadas do repositório","S3 object repositories":"Repositórios de objetos S3","PXE network profile preflight":"Verificação prévia do perfil de rede PXE","Remote job on this Client":"Tarefa remota neste Cliente","Authenticated Server job":"Tarefa autenticada do servidor","Client service status":"Estado do serviço do Cliente"},
  fr: {"Server setup":"Configuration du serveur","Client jobs":"Tâches du Client","Persisted remote jobs":"Tâches distantes enregistrées","Encrypted repository credentials":"Identifiants chiffrés du dépôt","S3 object repositories":"Dépôts d’objets S3","PXE network profile preflight":"Prévalidation du profil réseau PXE","Remote job on this Client":"Tâche distante sur ce Client","Authenticated Server job":"Tâche authentifiée du Server","Client service status":"État du service Client"},
  de: {"Server setup":"Servereinrichtung","Client jobs":"Client-Aufträge","Persisted remote jobs":"Gespeicherte Remote-Aufträge","Encrypted repository credentials":"Verschlüsselte Repository-Zugangsdaten","S3 object repositories":"S3-Objekt-Repositories","PXE network profile preflight":"Vorabprüfung des PXE-Netzwerkprofils","Remote job on this Client":"Remote-Auftrag auf diesem Client","Authenticated Server job":"Authentifizierter Server-Auftrag","Client service status":"Client-Dienststatus"},
  it: {"Server setup":"Configurazione del Server","Client jobs":"Attività del Client","Persisted remote jobs":"Attività remote salvate","Encrypted repository credentials":"Credenziali repository cifrate","S3 object repositories":"Repository di oggetti S3","PXE network profile preflight":"Verifica preliminare del profilo di rete PXE","Remote job on this Client":"Attività remota su questo Client","Authenticated Server job":"Attività autenticata del Server","Client service status":"Stato del servizio Client"},
  zh: {"Server setup":"服务器设置","Client jobs":"客户端任务","Persisted remote jobs":"已保存的远程任务","Encrypted repository credentials":"加密的存储库凭据","S3 object repositories":"S3 对象存储库","PXE network profile preflight":"PXE 网络配置预检","Remote job on this Client":"此客户端上的远程任务","Authenticated Server job":"已认证的服务器任务","Client service status":"客户端服务状态"},
  ja: {"Server setup":"サーバー設定","Client jobs":"クライアントジョブ","Persisted remote jobs":"保存済みリモートジョブ","Encrypted repository credentials":"暗号化されたリポジトリ認証情報","S3 object repositories":"S3 オブジェクトリポジトリ","PXE network profile preflight":"PXE ネットワークプロファイルの事前確認","Remote job on this Client":"この Client のリモートジョブ","Authenticated Server job":"認証済み Server ジョブ","Client service status":"Client サービスの状態"},
  ru: {"Server setup":"Настройка сервера","Client jobs":"Задания клиента","Persisted remote jobs":"Сохранённые удалённые задания","Encrypted repository credentials":"Зашифрованные учётные данные репозитория","S3 object repositories":"Репозитории объектов S3","PXE network profile preflight":"Предварительная проверка сетевого профиля PXE","Remote job on this Client":"Удалённое задание на этом клиенте","Authenticated Server job":"Аутентифицированное задание сервера","Client service status":"Состояние службы клиента"},
  ar: {"Server setup":"إعداد الخادم","Client jobs":"مهام العميل","Persisted remote jobs":"المهام البعيدة المحفوظة","Encrypted repository credentials":"بيانات اعتماد المستودع المشفرة","S3 object repositories":"مستودعات كائنات S3","PXE network profile preflight":"فحص تمهيدي لملف شبكة PXE","Remote job on this Client":"مهمة بعيدة على هذا العميل","Authenticated Server job":"مهمة خادم موثّقة","Client service status":"حالة خدمة العميل"},
  tr: {"Server setup":"Sunucu kurulumu","Client jobs":"İstemci işleri","Persisted remote jobs":"Kaydedilmiş uzak işler","Encrypted repository credentials":"Şifrelenmiş depo kimlik bilgileri","S3 object repositories":"S3 nesne depoları","PXE network profile preflight":"PXE ağ profili ön denetimi","Remote job on this Client":"Bu İstemcideki uzak iş","Authenticated Server job":"Kimliği doğrulanmış Sunucu işi","Client service status":"İstemci hizmet durumu"}
};

const APP_SELECT_TEXT = {
  es: {"Local repository":"Repositorio local","Select a disk image…":"Selecciona una imagen de disco…","Select local target…":"Selecciona el destino local…","Select Client interface/address…":"Selecciona la interfaz/dirección del cliente…","Select an interface/address…":"Selecciona una interfaz/dirección…","Select partition…":"Selecciona una partición…","Select an S3 repository…":"Selecciona un repositorio S3…","Select a QCOW2 image…":"Selecciona una imagen QCOW2…"},
  ca: {"Local repository":"Repositori local","Select a disk image…":"Selecciona una imatge de disc…","Select local target…":"Selecciona la destinació local…","Select Client interface/address…":"Selecciona la interfície/adreça del client…","Select an interface/address…":"Selecciona una interfície/adreça…","Select partition…":"Selecciona una partició…","Select an S3 repository…":"Selecciona un repositori S3…","Select a QCOW2 image…":"Selecciona una imatge QCOW2…"},
  gl: {"Local repository":"Repositorio local","Select a disk image…":"Selecciona unha imaxe de disco…","Select local target…":"Selecciona o destino local…","Select Client interface/address…":"Selecciona a interface/enderezo do cliente…","Select an interface/address…":"Selecciona unha interface/enderezo…","Select partition…":"Selecciona unha partición…","Select an S3 repository…":"Selecciona un repositorio S3…","Select a QCOW2 image…":"Selecciona unha imaxe QCOW2…"},
  eu: {"Local repository":"Biltegi lokala","Select a disk image…":"Hautatu disko-irudi bat…","Select local target…":"Hautatu helburu lokala…","Select Client interface/address…":"Hautatu bezeroaren interfazea/helbidea…","Select an interface/address…":"Hautatu interfazea/helbidea…","Select partition…":"Hautatu partizioa…","Select an S3 repository…":"Hautatu S3 biltegia…","Select a QCOW2 image…":"Hautatu QCOW2 irudia…"},
  pt: {"Local repository":"Repositório local","Select a disk image…":"Selecione uma imagem de disco…","Select local target…":"Selecione o destino local…","Select Client interface/address…":"Selecione a interface/endereço do Cliente…","Select an interface/address…":"Selecione uma interface/endereço…","Select partition…":"Selecione uma partição…","Select an S3 repository…":"Selecione um repositório S3…","Select a QCOW2 image…":"Selecione uma imagem QCOW2…"},
  fr: {"Local repository":"Dépôt local","Select a disk image…":"Sélectionner une image disque…","Select local target…":"Sélectionner la cible locale…","Select Client interface/address…":"Sélectionner l’interface/l’adresse du Client…","Select an interface/address…":"Sélectionner une interface/une adresse…","Select partition…":"Sélectionner une partition…","Select an S3 repository…":"Sélectionner un dépôt S3…","Select a QCOW2 image…":"Sélectionner une image QCOW2…"},
  de: {"Local repository":"Lokales Repository","Select a disk image…":"Festplatten-Image auswählen…","Select local target…":"Lokales Ziel auswählen…","Select Client interface/address…":"Client-Schnittstelle/-Adresse auswählen…","Select an interface/address…":"Schnittstelle/Adresse auswählen…","Select partition…":"Partition auswählen…","Select an S3 repository…":"S3-Repository auswählen…","Select a QCOW2 image…":"QCOW2-Image auswählen…"},
  it: {"Local repository":"Repository locale","Select a disk image…":"Seleziona un'immagine disco…","Select local target…":"Seleziona la destinazione locale…","Select Client interface/address…":"Seleziona l'interfaccia/indirizzo del Client…","Select an interface/address…":"Seleziona un'interfaccia/indirizzo…","Select partition…":"Seleziona una partizione…","Select an S3 repository…":"Seleziona un repository S3…","Select a QCOW2 image…":"Seleziona un'immagine QCOW2…"},
  zh: {"Local repository":"本地存储库","Select a disk image…":"选择磁盘映像…","Select local target…":"选择本地目标…","Select Client interface/address…":"选择客户端接口/地址…","Select an interface/address…":"选择接口/地址…","Select partition…":"选择分区…","Select an S3 repository…":"选择 S3 存储库…","Select a QCOW2 image…":"选择 QCOW2 映像…"},
  ja: {"Local repository":"ローカルリポジトリ","Select a disk image…":"ディスクイメージを選択…","Select local target…":"ローカルターゲットを選択…","Select Client interface/address…":"Client のインターフェース/アドレスを選択…","Select an interface/address…":"インターフェース/アドレスを選択…","Select partition…":"パーティションを選択…","Select an S3 repository…":"S3 リポジトリを選択…","Select a QCOW2 image…":"QCOW2 イメージを選択…"},
  ru: {"Local repository":"Локальный репозиторий","Select a disk image…":"Выберите образ диска…","Select local target…":"Выберите локальное назначение…","Select Client interface/address…":"Выберите интерфейс/адрес клиента…","Select an interface/address…":"Выберите интерфейс/адрес…","Select partition…":"Выберите раздел…","Select an S3 repository…":"Выберите репозиторий S3…","Select a QCOW2 image…":"Выберите образ QCOW2…"},
  ar: {"Local repository":"المستودع المحلي","Select a disk image…":"اختر صورة قرص…","Select local target…":"اختر الهدف المحلي…","Select Client interface/address…":"اختر واجهة/عنوان العميل…","Select an interface/address…":"اختر واجهة/عنواناً…","Select partition…":"اختر قسماً…","Select an S3 repository…":"اختر مستودع S3…","Select a QCOW2 image…":"اختر صورة QCOW2…"},
  tr: {"Local repository":"Yerel depo","Select a disk image…":"Bir disk görüntüsü seçin…","Select local target…":"Yerel hedefi seçin…","Select Client interface/address…":"İstemci arayüzünü/adresini seçin…","Select an interface/address…":"Bir arayüz/adres seçin…","Select partition…":"Bir bölüm seçin…","Select an S3 repository…":"Bir S3 deposu seçin…","Select a QCOW2 image…":"Bir QCOW2 görüntüsü seçin…"}
};
for (const [language, values] of Object.entries(APP_SELECT_TEXT)) {
  Object.assign(DICTS[language], values);
}

for (const [language, values] of Object.entries(APP_SECTION_TEXT)) {
  Object.assign(DICTS[language], values);
}

for (const [language, values] of Object.entries(APP_WORKFLOW_TEXT)) {
  Object.assign(DICTS[language], values);
}

for (const [language, values] of Object.entries(APP_FORM_LABELS)) {
  Object.assign(DICTS[language], values);
}

for (const [language, values] of Object.entries(APP_UI_TEXT)) {
  Object.assign(DICTS[language], values);
}


const APP_UI_TEXT_EXTRA = {
  es: {"Image":"Imagen","Source size":"Tamaño de origen","Encryption":"Cifrado","Artifacts":"Artefactos","Verification":"Verificación","Verify":"Verificar","Verified":"Verificado","Clients":"Clientes","Interrupted":"Interrumpido","ID":"ID","Endpoint":"Punto de conexión","Bucket / prefix":"Bucket / prefijo","Access":"Acceso","Actions":"Acciones","Provider":"Proveedor","Remote location":"Ubicación remota","Mount identity":"Identidad del montaje","State unknown":"Estado desconocido","Unmounted":"Desmontado","Mounted · identity verified":"Montado · identidad verificada","Mounted · unverified":"Montado · sin verificar","Timestamp":"Marca de tiempo","Progress":"Progreso","Operation ID":"ID de operación","Details":"Detalles","Control":"Control","Host IPv4 configuration":"Configuración IPv4 del equipo","Select profile…":"Selecciona un perfil…","Static IPv4":"IPv4 estática","Component":"Componente","Capability":"Capacidad"},
  ca: {"Image":"Imatge","Source size":"Mida d'origen","Encryption":"Xifratge","Artifacts":"Artefactes","Verification":"Verificació","Verify":"Verifica","Verified":"Verificat","Clients":"Clients","Interrupted":"Interromput","ID":"ID","Endpoint":"Punt final","Bucket / prefix":"Bucket / prefix","Access":"Accés","Actions":"Accions","Provider":"Proveïdor","Remote location":"Ubicació remota","Mount identity":"Identitat del muntatge","State unknown":"Estat desconegut","Unmounted":"Desmuntat","Mounted · identity verified":"Muntat · identitat verificada","Mounted · unverified":"Muntat · no verificat","Timestamp":"Marca de temps","Progress":"Progrés","Operation ID":"ID de l'operació","Details":"Detalls","Control":"Control","Host IPv4 configuration":"Configuració IPv4 de l'equip","Select profile…":"Selecciona un perfil…","Static IPv4":"IPv4 estàtica","Component":"Component","Capability":"Capacitat"},
  gl: {"Image":"Imaxe","Source size":"Tamaño da orixe","Encryption":"Cifrado","Artifacts":"Artefactos","Verification":"Verificación","Verify":"Verificar","Verified":"Verificado","Clients":"Clientes","Interrupted":"Interrompido","ID":"ID","Endpoint":"Punto de conexión","Bucket / prefix":"Bucket / prefixo","Access":"Acceso","Actions":"Accións","Provider":"Provedor","Remote location":"Localización remota","Mount identity":"Identidade da montaxe","State unknown":"Estado descoñecido","Unmounted":"Desmontado","Mounted · identity verified":"Montado · identidade verificada","Mounted · unverified":"Montado · sen verificar","Timestamp":"Marca temporal","Progress":"Progreso","Operation ID":"ID da operación","Details":"Detalles","Control":"Control","Host IPv4 configuration":"Configuración IPv4 do equipo","Select profile…":"Seleccionar perfil…","Static IPv4":"IPv4 estática","Component":"Compoñente","Capability":"Capacidade"},
  eu: {"Image":"Irudia","Source size":"Jatorrizko tamaina","Encryption":"Enkriptatzea","Artifacts":"Artefaktuak","Verification":"Egiaztapena","Verify":"Egiaztatu","Verified":"Egiaztatuta","Clients":"Bezeroak","Interrupted":"Etenda","ID":"IDa","Endpoint":"Amaiera-puntua","Bucket / prefix":"Bucket / aurrizkia","Access":"Sarbidea","Actions":"Ekintzak","Provider":"Hornitzailea","Remote location":"Urruneko kokapena","Mount identity":"Muntatze-identitatea","State unknown":"Egoera ezezaguna","Unmounted":"Desmuntatuta","Mounted · identity verified":"Muntatuta · identitatea egiaztatuta","Mounted · unverified":"Muntatuta · egiaztatu gabe","Timestamp":"Denbora-marka","Progress":"Aurrerapena","Operation ID":"Eragiketaren IDa","Details":"Xehetasunak","Control":"Kontrola","Host IPv4 configuration":"Ostalariaren IPv4 konfigurazioa","Select profile…":"Hautatu profila…","Static IPv4":"IPv4 estatikoa","Component":"Osagaia","Capability":"Gaitasuna"},
  pt: {"Image":"Imagem","Source size":"Tamanho da origem","Encryption":"Encriptação","Artifacts":"Artefactos","Verification":"Verificação","Verify":"Verificar","Verified":"Verificado","Clients":"Clientes","Interrupted":"Interrompido","ID":"ID","Endpoint":"Ponto final","Bucket / prefix":"Bucket / prefixo","Access":"Acesso","Actions":"Ações","Provider":"Fornecedor","Remote location":"Localização remota","Mount identity":"Identidade da montagem","State unknown":"Estado desconhecido","Unmounted":"Desmontado","Mounted · identity verified":"Montado · identidade verificada","Mounted · unverified":"Montado · não verificado","Timestamp":"Carimbo temporal","Progress":"Progresso","Operation ID":"ID da operação","Details":"Detalhes","Control":"Controlo","Host IPv4 configuration":"Configuração IPv4 do equipamento","Select profile…":"Selecionar perfil…","Static IPv4":"IPv4 estático","Component":"Componente","Capability":"Capacidade"},
  fr: {"Image":"Image","Source size":"Taille source","Encryption":"Chiffrement","Artifacts":"Artefacts","Verification":"Vérification","Verify":"Vérifier","Verified":"Vérifié","Clients":"Clients","Interrupted":"Interrompu","ID":"ID","Endpoint":"Point de terminaison","Bucket / prefix":"Bucket / préfixe","Access":"Accès","Actions":"Actions","Provider":"Fournisseur","Remote location":"Emplacement distant","Mount identity":"Identité du montage","State unknown":"État inconnu","Unmounted":"Démonté","Mounted · identity verified":"Monté · identité vérifiée","Mounted · unverified":"Monté · non vérifié","Timestamp":"Horodatage","Progress":"Progression","Operation ID":"ID d’opération","Details":"Détails","Control":"Contrôle","Host IPv4 configuration":"Configuration IPv4 de l’hôte","Select profile…":"Sélectionner un profil…","Static IPv4":"IPv4 statique","Component":"Composant","Capability":"Capacité"},
  de: {"Image":"Image","Source size":"Quellgröße","Encryption":"Verschlüsselung","Artifacts":"Artefakte","Verification":"Überprüfung","Verify":"Überprüfen","Verified":"Verifiziert","Clients":"Clients","Interrupted":"Unterbrochen","ID":"ID","Endpoint":"Endpunkt","Bucket / prefix":"Bucket / Präfix","Access":"Zugriff","Actions":"Aktionen","Provider":"Anbieter","Remote location":"Remote-Speicherort","Mount identity":"Mount-Identität","State unknown":"Status unbekannt","Unmounted":"Ausgehängt","Mounted · identity verified":"Eingehängt · Identität verifiziert","Mounted · unverified":"Eingehängt · nicht verifiziert","Timestamp":"Zeitstempel","Progress":"Fortschritt","Operation ID":"Vorgangs-ID","Details":"Details","Control":"Steuerung","Host IPv4 configuration":"IPv4-Konfiguration des Hosts","Select profile…":"Profil auswählen…","Static IPv4":"Statische IPv4","Component":"Komponente","Capability":"Funktion"},
  it: {"Image":"Immagine","Source size":"Dimensione sorgente","Encryption":"Cifratura","Artifacts":"Artefatti","Verification":"Verifica","Verify":"Verifica","Verified":"Verificato","Clients":"Client","Interrupted":"Interrotto","ID":"ID","Endpoint":"Endpoint","Bucket / prefix":"Bucket / prefisso","Access":"Accesso","Actions":"Azioni","Provider":"Provider","Remote location":"Posizione remota","Mount identity":"Identità del mount","State unknown":"Stato sconosciuto","Unmounted":"Smontato","Mounted · identity verified":"Montato · identità verificata","Mounted · unverified":"Montato · non verificato","Timestamp":"Data e ora","Progress":"Avanzamento","Operation ID":"ID operazione","Details":"Dettagli","Control":"Controllo","Host IPv4 configuration":"Configurazione IPv4 dell'host","Select profile…":"Seleziona un profilo…","Static IPv4":"IPv4 statico","Component":"Componente","Capability":"Funzionalità"},
  zh: {"Image":"映像","Source size":"源大小","Encryption":"加密","Artifacts":"文件","Verification":"验证","Verify":"验证","Verified":"已验证","Clients":"客户端","Interrupted":"已中断","ID":"ID","Endpoint":"终端节点","Bucket / prefix":"存储桶 / 前缀","Access":"访问权限","Actions":"操作","Provider":"提供方","Remote location":"远程位置","Mount identity":"挂载身份","State unknown":"状态未知","Unmounted":"未挂载","Mounted · identity verified":"已挂载 · 身份已验证","Mounted · unverified":"已挂载 · 未验证","Timestamp":"时间戳","Progress":"进度","Operation ID":"操作 ID","Details":"详细信息","Control":"控制","Host IPv4 configuration":"主机 IPv4 配置","Select profile…":"选择配置文件…","Static IPv4":"静态 IPv4","Component":"组件","Capability":"功能"},
  ja: {"Image":"イメージ","Source size":"ソースサイズ","Encryption":"暗号化","Artifacts":"成果物","Verification":"検証","Verify":"検証","Verified":"検証済み","Clients":"Client","Interrupted":"中断","ID":"ID","Endpoint":"エンドポイント","Bucket / prefix":"バケット / プレフィックス","Access":"アクセス","Actions":"操作","Provider":"プロバイダー","Remote location":"リモートの場所","Mount identity":"マウントID","State unknown":"状態不明","Unmounted":"アンマウント済み","Mounted · identity verified":"マウント済み · ID検証済み","Mounted · unverified":"マウント済み · 未検証","Timestamp":"タイムスタンプ","Progress":"進行状況","Operation ID":"操作ID","Details":"詳細","Control":"制御","Host IPv4 configuration":"ホストのIPv4設定","Select profile…":"プロファイルを選択…","Static IPv4":"静的IPv4","Component":"コンポーネント","Capability":"機能"},
  ru: {"Image":"Образ","Source size":"Размер источника","Encryption":"Шифрование","Artifacts":"Артефакты","Verification":"Проверка","Verify":"Проверить","Verified":"Проверено","Clients":"Клиенты","Interrupted":"Прервано","ID":"ID","Endpoint":"Конечная точка","Bucket / prefix":"Bucket / префикс","Access":"Доступ","Actions":"Действия","Provider":"Поставщик","Remote location":"Удалённое расположение","Mount identity":"Идентификатор монтирования","State unknown":"Состояние неизвестно","Unmounted":"Не смонтировано","Mounted · identity verified":"Смонтировано · идентичность проверена","Mounted · unverified":"Смонтировано · не проверено","Timestamp":"Временная метка","Progress":"Ход выполнения","Operation ID":"ID операции","Details":"Подробности","Control":"Управление","Host IPv4 configuration":"Настройка IPv4 узла","Select profile…":"Выберите профиль…","Static IPv4":"Статический IPv4","Component":"Компонент","Capability":"Возможность"},
  ar: {"Image":"الصورة","Source size":"حجم المصدر","Encryption":"التشفير","Artifacts":"الملفات","Verification":"التحقق","Verify":"تحقق","Verified":"تم التحقق","Clients":"العملاء","Interrupted":"متوقف","ID":"المعرّف","Endpoint":"نقطة النهاية","Bucket / prefix":"الحاوية / البادئة","Access":"الوصول","Actions":"الإجراءات","Provider":"المزوّد","Remote location":"الموقع البعيد","Mount identity":"هوية التحميل","State unknown":"الحالة غير معروفة","Unmounted":"غير محمّل","Mounted · identity verified":"محمّل · تم التحقق من الهوية","Mounted · unverified":"محمّل · لم يتم التحقق","Timestamp":"الطابع الزمني","Progress":"التقدم","Operation ID":"معرّف العملية","Details":"التفاصيل","Control":"التحكم","Host IPv4 configuration":"إعداد IPv4 للمضيف","Select profile…":"اختر ملف تعريف…","Static IPv4":"IPv4 ثابت","Component":"المكوّن","Capability":"الإمكانات"},
  tr: {"Image":"Görüntü","Source size":"Kaynak boyutu","Encryption":"Şifreleme","Artifacts":"Yapıtlar","Verification":"Doğrulama","Verify":"Doğrula","Verified":"Doğrulandı","Clients":"İstemciler","Interrupted":"Kesintiye uğradı","ID":"Kimlik","Endpoint":"Uç nokta","Bucket / prefix":"Bucket / önek","Access":"Erişim","Actions":"Eylemler","Provider":"Sağlayıcı","Remote location":"Uzak konum","Mount identity":"Bağlama kimliği","State unknown":"Durum bilinmiyor","Unmounted":"Bağlı değil","Mounted · identity verified":"Bağlı · kimlik doğrulandı","Mounted · unverified":"Bağlı · doğrulanmadı","Timestamp":"Zaman damgası","Progress":"İlerleme","Operation ID":"İşlem kimliği","Details":"Ayrıntılar","Control":"Denetim","Host IPv4 configuration":"Ana makine IPv4 yapılandırması","Select profile…":"Profil seç…","Static IPv4":"Statik IPv4","Component":"Bileşen","Capability":"Yetenek"}
};
for (const [language, values] of Object.entries(APP_UI_TEXT_EXTRA)) {
  Object.assign(DICTS[language], values);
}

const APP_UI_TEXT_OPERATIONS = {
 es: {"Verified S3 P2V export":"Exportación P2V verificada desde S3","S3 source repository":"Repositorio S3 de origen","Committed P2V image":"Imagen P2V confirmada","Filesystem destination repository":"Repositorio de destino del sistema de archivos","Self-contained recovery media":"Medio de recuperación autónomo","Base Feclora Live ISO path":"Ruta de la ISO base de Feclora Live","Whole-disk image to embed":"Imagen de disco completo que se incluirá","Target disk WWN (recommended)":"WWN del disco de destino (recomendado)","Target disk serial (alternative or additional selector)":"Número de serie del disco de destino (alternativo o adicional)","Confirm ISO creation":"Confirmar creación de ISO","Typed build confirmation":"Confirmación escrita de creación","Image identifier":"Identificador de imagen","Partition identifier":"Identificador de partición","P2V output":"Resultado P2V","Destination disk is too small":"El disco de destino es demasiado pequeño","Read-only restore layout preview":"Vista previa de solo lectura de la distribución de restauración","Destructive operation":"Operación destructiva","Typed confirmation":"Confirmación escrita","Operation progress":"Progreso de la operación","Operation in progress":"Operación en curso"},
 ca: {"Verified S3 P2V export":"Exportació P2V verificada des de S3","S3 source repository":"Repositori S3 d'origen","Committed P2V image":"Imatge P2V confirmada","Filesystem destination repository":"Repositori de destinació del sistema de fitxers","Self-contained recovery media":"Mitjà de recuperació autònom","Base Feclora Live ISO path":"Camí de la ISO base de Feclora Live","Whole-disk image to embed":"Imatge de disc sencer que s'hi inclourà","Target disk WWN (recommended)":"WWN del disc de destinació (recomanat)","Target disk serial (alternative or additional selector)":"Número de sèrie del disc de destinació (alternatiu o addicional)","Confirm ISO creation":"Confirma la creació de la ISO","Typed build confirmation":"Confirmació escrita de construcció","Image identifier":"Identificador de la imatge","Partition identifier":"Identificador de la partició","P2V output":"Resultat P2V","Destination disk is too small":"El disc de destinació és massa petit","Read-only restore layout preview":"Previsualització de només lectura de la distribució de restauració","Destructive operation":"Operació destructiva","Typed confirmation":"Confirmació escrita","Operation progress":"Progrés de l'operació","Operation in progress":"Operació en curs"},
 gl: {"Verified S3 P2V export":"Exportación P2V verificada desde S3","S3 source repository":"Repositorio S3 de orixe","Committed P2V image":"Imaxe P2V confirmada","Filesystem destination repository":"Repositorio de destino do sistema de ficheiros","Self-contained recovery media":"Medio de recuperación autónomo","Base Feclora Live ISO path":"Ruta da ISO base de Feclora Live","Whole-disk image to embed":"Imaxe de disco completo que se incluirá","Target disk WWN (recommended)":"WWN do disco de destino (recomendado)","Target disk serial (alternative or additional selector)":"Número de serie do disco de destino (alternativo ou adicional)","Confirm ISO creation":"Confirmar creación da ISO","Typed build confirmation":"Confirmación escrita de creación","Image identifier":"Identificador da imaxe","Partition identifier":"Identificador da partición","P2V output":"Resultado P2V","Destination disk is too small":"O disco de destino é demasiado pequeno","Read-only restore layout preview":"Vista previa de só lectura da distribución de restauración","Destructive operation":"Operación destrutiva","Typed confirmation":"Confirmación escrita","Operation progress":"Progreso da operación","Operation in progress":"Operación en curso"},
 eu: {"Verified S3 P2V export":"S3tik egiaztatutako P2V esportazioa","S3 source repository":"S3 iturburu-biltegia","Committed P2V image":"Berretsitako P2V irudia","Filesystem destination repository":"Fitxategi-sistemako helburu-biltegia","Self-contained recovery media":"Berreskuratze-euskarri autonomoa","Base Feclora Live ISO path":"Feclora Live oinarrizko ISOaren bidea","Whole-disk image to embed":"Txertatu beharreko disko osoko irudia","Target disk WWN (recommended)":"Helburuko diskoaren WWN (gomendatua)","Target disk serial (alternative or additional selector)":"Helburuko diskoaren serie-zenbakia (ordezkoa edo gehigarria)","Confirm ISO creation":"Berretsi ISOaren sorrera","Typed build confirmation":"Idatzizko eraikitze-berrespena","Image identifier":"Irudiaren identifikatzailea","Partition identifier":"Partizioaren identifikatzailea","P2V output":"P2V irteera","Destination disk is too small":"Helburuko diskoa txikiegia da","Read-only restore layout preview":"Berrezarpen-diseinuaren irakurtzeko soilik aurrebista","Destructive operation":"Eragiketa suntsitzailea","Typed confirmation":"Idatzizko berrespena","Operation progress":"Eragiketaren aurrerapena","Operation in progress":"Eragiketa martxan"},
 pt: {"Verified S3 P2V export":"Exportação P2V verificada do S3","S3 source repository":"Repositório S3 de origem","Committed P2V image":"Imagem P2V confirmada","Filesystem destination repository":"Repositório de destino do sistema de ficheiros","Self-contained recovery media":"Suporte de recuperação autónomo","Base Feclora Live ISO path":"Caminho da ISO base do Feclora Live","Whole-disk image to embed":"Imagem de disco completo a incorporar","Target disk WWN (recommended)":"WWN do disco de destino (recomendado)","Target disk serial (alternative or additional selector)":"Número de série do disco de destino (alternativo ou adicional)","Confirm ISO creation":"Confirmar criação da ISO","Typed build confirmation":"Confirmação escrita da criação","Image identifier":"Identificador da imagem","Partition identifier":"Identificador da partição","P2V output":"Resultado P2V","Destination disk is too small":"O disco de destino é demasiado pequeno","Read-only restore layout preview":"Pré-visualização só de leitura da disposição do restauro","Destructive operation":"Operação destrutiva","Typed confirmation":"Confirmação escrita","Operation progress":"Progresso da operação","Operation in progress":"Operação em curso"},
 fr: {"Verified S3 P2V export":"Exportation P2V S3 vérifiée","S3 source repository":"Dépôt source S3","Committed P2V image":"Image P2V validée","Filesystem destination repository":"Dépôt de destination du système de fichiers","Self-contained recovery media":"Support de récupération autonome","Base Feclora Live ISO path":"Chemin de l’ISO Feclora Live de base","Whole-disk image to embed":"Image disque entière à intégrer","Target disk WWN (recommended)":"WWN du disque cible (recommandé)","Target disk serial (alternative or additional selector)":"Numéro de série du disque cible (autre sélecteur ou complément)","Confirm ISO creation":"Confirmer la création de l’ISO","Typed build confirmation":"Confirmation écrite de création","Image identifier":"Identifiant de l’image","Partition identifier":"Identifiant de partition","P2V output":"Sortie P2V","Destination disk is too small":"Le disque de destination est trop petit","Read-only restore layout preview":"Aperçu en lecture seule de la disposition de restauration","Destructive operation":"Opération destructive","Typed confirmation":"Confirmation saisie","Operation progress":"Progression de l’opération","Operation in progress":"Opération en cours"},
 de: {"Verified S3 P2V export":"Verifizierter S3-P2V-Export","S3 source repository":"S3-Quellrepository","Committed P2V image":"Veröffentlichtes P2V-Image","Filesystem destination repository":"Dateisystem-Zielrepository","Self-contained recovery media":"Eigenständiges Wiederherstellungsmedium","Base Feclora Live ISO path":"Pfad zur Feclora-Live-Basis-ISO","Whole-disk image to embed":"Einzubettendes vollständiges Festplatten-Image","Target disk WWN (recommended)":"WWN der Zielfestplatte (empfohlen)","Target disk serial (alternative or additional selector)":"Seriennummer der Zielfestplatte (alternativ oder zusätzlich)","Confirm ISO creation":"ISO-Erstellung bestätigen","Typed build confirmation":"Eingegebene Erstellungsbestätigung","Image identifier":"Image-Kennung","Partition identifier":"Partitionskennung","P2V output":"P2V-Ausgabe","Destination disk is too small":"Zielfestplatte ist zu klein","Read-only restore layout preview":"Schreibgeschützte Vorschau des Wiederherstellungslayouts","Destructive operation":"Destruktiver Vorgang","Typed confirmation":"Eingegebene Bestätigung","Operation progress":"Vorgangsfortschritt","Operation in progress":"Vorgang läuft"},
 it: {"Verified S3 P2V export":"Esportazione P2V S3 verificata","S3 source repository":"Repository S3 sorgente","Committed P2V image":"Immagine P2V pubblicata","Filesystem destination repository":"Repository di destinazione su file system","Self-contained recovery media":"Supporto di ripristino autonomo","Base Feclora Live ISO path":"Percorso ISO base di Feclora Live","Whole-disk image to embed":"Immagine dell'intero disco da incorporare","Target disk WWN (recommended)":"WWN del disco di destinazione (consigliato)","Target disk serial (alternative or additional selector)":"Numero di serie del disco di destinazione (alternativo o aggiuntivo)","Confirm ISO creation":"Conferma creazione ISO","Typed build confirmation":"Conferma di creazione digitata","Image identifier":"Identificatore immagine","Partition identifier":"Identificatore partizione","P2V output":"Output P2V","Destination disk is too small":"Il disco di destinazione è troppo piccolo","Read-only restore layout preview":"Anteprima di sola lettura del layout di ripristino","Destructive operation":"Operazione distruttiva","Typed confirmation":"Conferma digitata","Operation progress":"Avanzamento operazione","Operation in progress":"Operazione in corso"},
 zh: {"Verified S3 P2V export":"已验证的 S3 P2V 导出","S3 source repository":"S3 源存储库","Committed P2V image":"已提交的 P2V 映像","Filesystem destination repository":"文件系统目标存储库","Self-contained recovery media":"独立恢复介质","Base Feclora Live ISO path":"Feclora Live 基础 ISO 路径","Whole-disk image to embed":"要嵌入的整盘映像","Target disk WWN (recommended)":"目标磁盘 WWN（推荐）","Target disk serial (alternative or additional selector)":"目标磁盘序列号（替代或附加选择器）","Confirm ISO creation":"确认创建 ISO","Typed build confirmation":"输入创建确认文本","Image identifier":"映像标识符","Partition identifier":"分区标识符","P2V output":"P2V 输出","Destination disk is too small":"目标磁盘太小","Read-only restore layout preview":"只读恢复布局预览","Destructive operation":"破坏性操作","Typed confirmation":"输入确认文本","Operation progress":"操作进度","Operation in progress":"操作进行中"},
 ja: {"Verified S3 P2V export":"検証済み S3 P2V エクスポート","S3 source repository":"S3 ソースリポジトリ","Committed P2V image":"確定済み P2V イメージ","Filesystem destination repository":"ファイルシステムの宛先リポジトリ","Self-contained recovery media":"自己完結型リカバリメディア","Base Feclora Live ISO path":"Feclora Live ベース ISO のパス","Whole-disk image to embed":"埋め込むディスク全体のイメージ","Target disk WWN (recommended)":"対象ディスクの WWN（推奨）","Target disk serial (alternative or additional selector)":"対象ディスクのシリアル番号（代替または追加指定）","Confirm ISO creation":"ISO の作成を確認","Typed build confirmation":"入力による作成確認","Image identifier":"イメージ識別子","Partition identifier":"パーティション識別子","P2V output":"P2V 出力","Destination disk is too small":"宛先ディスクの容量が不足しています","Read-only restore layout preview":"読み取り専用の復元レイアウトプレビュー","Destructive operation":"破壊的な操作","Typed confirmation":"入力確認","Operation progress":"操作の進行状況","Operation in progress":"操作中"},
 ru: {"Verified S3 P2V export":"Проверенный экспорт P2V из S3","S3 source repository":"Исходный репозиторий S3","Committed P2V image":"Зафиксированный образ P2V","Filesystem destination repository":"Целевой репозиторий файловой системы","Self-contained recovery media":"Автономный носитель восстановления","Base Feclora Live ISO path":"Путь к базовому ISO Feclora Live","Whole-disk image to embed":"Образ всего диска для включения","Target disk WWN (recommended)":"WWN целевого диска (рекомендуется)","Target disk serial (alternative or additional selector)":"Серийный номер целевого диска (альтернативный или дополнительный)","Confirm ISO creation":"Подтвердить создание ISO","Typed build confirmation":"Введённое подтверждение сборки","Image identifier":"Идентификатор образа","Partition identifier":"Идентификатор раздела","P2V output":"Результат P2V","Destination disk is too small":"Целевой диск слишком мал","Read-only restore layout preview":"Предварительный просмотр разметки восстановления (только чтение)","Destructive operation":"Разрушающая операция","Typed confirmation":"Введённое подтверждение","Operation progress":"Ход выполнения операции","Operation in progress":"Операция выполняется"},
 ar: {"Verified S3 P2V export":"تصدير P2V موثّق من S3","S3 source repository":"مستودع مصدر S3","Committed P2V image":"صورة P2V معتمدة","Filesystem destination repository":"مستودع وجهة نظام الملفات","Self-contained recovery media":"وسيط استرداد مستقل","Base Feclora Live ISO path":"مسار ISO الأساسي لـ Feclora Live","Whole-disk image to embed":"صورة القرص بالكامل للتضمين","Target disk WWN (recommended)":"WWN للقرص الهدف (موصى به)","Target disk serial (alternative or additional selector)":"الرقم التسلسلي للقرص الهدف (بديل أو محدد إضافي)","Confirm ISO creation":"تأكيد إنشاء ISO","Typed build confirmation":"تأكيد الإنشاء المكتوب","Image identifier":"معرّف الصورة","Partition identifier":"معرّف القسم","P2V output":"مخرجات P2V","Destination disk is too small":"القرص الهدف صغير جداً","Read-only restore layout preview":"معاينة تخطيط الاستعادة للقراءة فقط","Destructive operation":"عملية مدمّرة","Typed confirmation":"التأكيد المكتوب","Operation progress":"تقدم العملية","Operation in progress":"العملية قيد التنفيذ"},
 tr: {"Verified S3 P2V export":"Doğrulanmış S3 P2V dışa aktarımı","S3 source repository":"S3 kaynak deposu","Committed P2V image":"Yayımlanmış P2V görüntüsü","Filesystem destination repository":"Dosya sistemi hedef deposu","Self-contained recovery media":"Bağımsız kurtarma ortamı","Base Feclora Live ISO path":"Feclora Live temel ISO yolu","Whole-disk image to embed":"Eklenecek tüm disk görüntüsü","Target disk WWN (recommended)":"Hedef disk WWN (önerilir)","Target disk serial (alternative or additional selector)":"Hedef disk seri numarası (alternatif veya ek seçici)","Confirm ISO creation":"ISO oluşturmayı onayla","Typed build confirmation":"Yazılı oluşturma onayı","Image identifier":"Görüntü tanımlayıcısı","Partition identifier":"Bölüm tanımlayıcısı","P2V output":"P2V çıktısı","Destination disk is too small":"Hedef disk çok küçük","Read-only restore layout preview":"Salt okunur geri yükleme düzeni önizlemesi","Destructive operation":"Yıkıcı işlem","Typed confirmation":"Yazılı onay","Operation progress":"İşlem ilerlemesi","Operation in progress":"İşlem sürüyor"}
};
for (const [language, values] of Object.entries(APP_UI_TEXT_OPERATIONS)) {
  Object.assign(DICTS[language], values);
}

const APP_UI_TEXT_REMOTE = {
 es: {"Selected Client MAC addresses":"Direcciones MAC de los Clientes seleccionados","Server network interface":"Interfaz de red del Servidor","Administratively scoped multicast group":"Grupo multicast de ámbito administrativo","UDPcast even portbase":"Puerto base par de UDPcast","Multicast transport limitation":"Limitación del transporte multicast","Start policy":"Política de inicio","Minimum READY Clients":"Número mínimo de Clientes READY","Start deadline (local time)":"Fecha límite de inicio (hora local)","Final action on each successful Client":"Acción final en cada Cliente correcto","Job definition persisted":"Definición de tarea guardada","Persisted remote deployment jobs":"Tareas de despliegue remotas guardadas","Client list truncated":"Lista de Clientes truncada","Multicast network warnings":"Advertencias de red multicast","Multicast preflight failed":"Falló la comprobación previa de multicast","Execution error":"Error de ejecución","Feclora deployment history":"Historial de despliegues de Feclora","Repository ID":"ID del repositorio","Server hostname or IPv4 address":"Nombre de host o dirección IPv4 del Servidor","Username":"Nombre de usuario","Encrypted SSH private-key credential":"Credencial cifrada de clave privada SSH","Encrypted pinned SSH known_hosts credential":"Credencial cifrada de known_hosts SSH fijado","Encrypted SMB credentials":"Credenciales SMB cifradas","Port (optional)":"Puerto (opcional)","Mount access":"Acceso de montaje","Credential ID":"ID de credencial","Credential type":"Tipo de credencial","Protected source file path":"Ruta del archivo de origen protegido","Encrypted repository credentials":"Credenciales cifradas del repositorio","S3 endpoint URL (optional; empty for AWS S3)":"URL del endpoint S3 (opcional; vacío para AWS S3)","Region":"Región","Bucket":"Bucket","Object prefix":"Prefijo de objeto","Encrypted S3 credential":"Credencial S3 cifrada","S3 object repositories":"Repositorios de objetos S3","Remote image repositories":"Repositorios remotos de imágenes","Local operation history":"Historial de operaciones locales"},
 ca: {"Selected Client MAC addresses":"Adreces MAC dels Clients seleccionats","Server network interface":"Interfície de xarxa del Servidor","Administratively scoped multicast group":"Grup multicast d'àmbit administratiu","UDPcast even portbase":"Port base parell d'UDPcast","Multicast transport limitation":"Limitació del transport multicast","Start policy":"Política d'inici","Minimum READY Clients":"Nombre mínim de Clients READY","Start deadline (local time)":"Data límit d'inici (hora local)","Final action on each successful Client":"Acció final a cada Client correcte","Job definition persisted":"Definició de tasca desada","Persisted remote deployment jobs":"Tasques de desplegament remotes desades","Client list truncated":"Llista de Clients truncada","Multicast network warnings":"Avisos de xarxa multicast","Multicast preflight failed":"Ha fallat la comprovació prèvia de multicast","Execution error":"Error d'execució","Feclora deployment history":"Historial de desplegaments de Feclora","Repository ID":"ID del repositori","Server hostname or IPv4 address":"Nom d'amfitrió o adreça IPv4 del Servidor","Username":"Nom d'usuari","Encrypted SSH private-key credential":"Credencial xifrada de clau privada SSH","Encrypted pinned SSH known_hosts credential":"Credencial xifrada de known_hosts SSH fixat","Encrypted SMB credentials":"Credencials SMB xifrades","Port (optional)":"Port (opcional)","Mount access":"Accés de muntatge","Credential ID":"ID de credencial","Credential type":"Tipus de credencial","Protected source file path":"Camí del fitxer d'origen protegit","Encrypted repository credentials":"Credencials xifrades del repositori","S3 endpoint URL (optional; empty for AWS S3)":"URL de l'endpoint S3 (opcional; buit per a AWS S3)","Region":"Regió","Bucket":"Bucket","Object prefix":"Prefix de l'objecte","Encrypted S3 credential":"Credencial S3 xifrada","S3 object repositories":"Repositoris d'objectes S3","Remote image repositories":"Repositoris remots d'imatges","Local operation history":"Historial d'operacions locals"},
 gl: {"Selected Client MAC addresses":"Enderezos MAC dos Clientes seleccionados","Server network interface":"Interface de rede do Servidor","Administratively scoped multicast group":"Grupo multicast de ámbito administrativo","UDPcast even portbase":"Porto base par de UDPcast","Multicast transport limitation":"Limitación do transporte multicast","Start policy":"Política de inicio","Minimum READY Clients":"Número mínimo de Clientes READY","Start deadline (local time)":"Prazo de inicio (hora local)","Final action on each successful Client":"Acción final en cada Cliente correcto","Job definition persisted":"Definición da tarefa gardada","Persisted remote deployment jobs":"Tarefas remotas de despregamento gardadas","Client list truncated":"Lista de Clientes truncada","Multicast network warnings":"Avisos da rede multicast","Multicast preflight failed":"Fallou a comprobación previa de multicast","Execution error":"Erro de execución","Feclora deployment history":"Historial de despregamento de Feclora","Repository ID":"ID do repositorio","Server hostname or IPv4 address":"Nome de host ou enderezo IPv4 do Servidor","Username":"Nome de usuario","Encrypted SSH private-key credential":"Credencial cifrada da clave privada SSH","Encrypted pinned SSH known_hosts credential":"Credencial cifrada de known_hosts SSH fixado","Encrypted SMB credentials":"Credenciais SMB cifradas","Port (optional)":"Porto (opcional)","Mount access":"Acceso de montaxe","Credential ID":"ID da credencial","Credential type":"Tipo de credencial","Protected source file path":"Ruta do ficheiro de orixe protexido","Encrypted repository credentials":"Credenciais cifradas do repositorio","S3 endpoint URL (optional; empty for AWS S3)":"URL do endpoint S3 (opcional; baleiro para AWS S3)","Region":"Rexión","Bucket":"Bucket","Object prefix":"Prefixo do obxecto","Encrypted S3 credential":"Credencial S3 cifrada","S3 object repositories":"Repositorios de obxectos S3","Remote image repositories":"Repositorios remotos de imaxes","Local operation history":"Historial de operacións locais"},
 eu: {"Selected Client MAC addresses":"Hautatutako Bezeroen MAC helbideak","Server network interface":"Zerbitzariaren sare-interfazea","Administratively scoped multicast group":"Administrazio-esparruko multicast taldea","UDPcast even portbase":"UDPcast-en oinarri-portu bikoitia","Multicast transport limitation":"Multicast garraioaren muga","Start policy":"Hasieratze-politika","Minimum READY Clients":"Gutxieneko READY Bezero kopurua","Start deadline (local time)":"Hasierako epemuga (tokiko ordua)","Final action on each successful Client":"Bezero arrakastatsu bakoitzaren azken ekintza","Job definition persisted":"Lanaren definizioa gorde da","Persisted remote deployment jobs":"Gordetako urruneko inplementazio-lanak","Client list truncated":"Bezeroen zerrenda moztuta","Multicast network warnings":"Multicast sareko oharrak","Multicast preflight failed":"Multicast aurre-egiaztapenak huts egin du","Execution error":"Exekuzio-errorea","Feclora deployment history":"Feclora inplementazio-historia","Repository ID":"Biltegiaren IDa","Server hostname or IPv4 address":"Zerbitzariaren ostalari-izena edo IPv4 helbidea","Username":"Erabiltzaile-izena","Encrypted SSH private-key credential":"SSH gako pribatuaren kredentzial enkriptatua","Encrypted pinned SSH known_hosts credential":"Finkatutako SSH known_hosts kredentzial enkriptatua","Encrypted SMB credentials":"SMB kredentzial enkriptatuak","Port (optional)":"Ataka (aukerakoa)","Mount access":"Muntatze-sarbidea","Credential ID":"Kredentzialaren IDa","Credential type":"Kredentzial mota","Protected source file path":"Babestutako iturburu-fitxategiaren bidea","Encrypted repository credentials":"Biltegiko kredentzial enkriptatuak","S3 endpoint URL (optional; empty for AWS S3)":"S3 endpoint URLa (aukerakoa; hutsik AWS S3rako)","Region":"Eskualdea","Bucket":"Bucket","Object prefix":"Objektu-aurrizkia","Encrypted S3 credential":"S3 kredentzial enkriptatua","S3 object repositories":"S3 objektu-biltegiak","Remote image repositories":"Urruneko irudi-biltegiak","Local operation history":"Eragiketa lokalen historia"},
 pt: {"Selected Client MAC addresses":"Endereços MAC dos Clientes selecionados","Server network interface":"Interface de rede do Servidor","Administratively scoped multicast group":"Grupo multicast de âmbito administrativo","UDPcast even portbase":"Porta base par do UDPcast","Multicast transport limitation":"Limitação do transporte multicast","Start policy":"Política de início","Minimum READY Clients":"Número mínimo de Clientes READY","Start deadline (local time)":"Prazo de início (hora local)","Final action on each successful Client":"Ação final em cada Cliente com sucesso","Job definition persisted":"Definição da tarefa guardada","Persisted remote deployment jobs":"Tarefas de implementação remota guardadas","Client list truncated":"Lista de Clientes truncada","Multicast network warnings":"Avisos da rede multicast","Multicast preflight failed":"Falha na verificação prévia do multicast","Execution error":"Erro de execução","Feclora deployment history":"Histórico de implementação do Feclora","Repository ID":"ID do repositório","Server hostname or IPv4 address":"Nome do anfitrião ou endereço IPv4 do Servidor","Username":"Nome de utilizador","Encrypted SSH private-key credential":"Credencial de chave privada SSH encriptada","Encrypted pinned SSH known_hosts credential":"Credencial known_hosts SSH fixada e encriptada","Encrypted SMB credentials":"Credenciais SMB encriptadas","Port (optional)":"Porta (opcional)","Mount access":"Acesso de montagem","Credential ID":"ID da credencial","Credential type":"Tipo de credencial","Protected source file path":"Caminho do ficheiro de origem protegido","Encrypted repository credentials":"Credenciais encriptadas do repositório","S3 endpoint URL (optional; empty for AWS S3)":"URL do endpoint S3 (opcional; vazio para AWS S3)","Region":"Região","Bucket":"Bucket","Object prefix":"Prefixo do objeto","Encrypted S3 credential":"Credencial S3 encriptada","S3 object repositories":"Repositórios de objetos S3","Remote image repositories":"Repositórios remotos de imagens","Local operation history":"Histórico de operações locais"},
 fr: {"Selected Client MAC addresses":"Adresses MAC des Clients sélectionnés","Server network interface":"Interface réseau du Serveur","Administratively scoped multicast group":"Groupe multicast à portée administrative","UDPcast even portbase":"Port de base pair UDPcast","Multicast transport limitation":"Limite du transport multicast","Start policy":"Politique de démarrage","Minimum READY Clients":"Nombre minimal de Clients READY","Start deadline (local time)":"Échéance de démarrage (heure locale)","Final action on each successful Client":"Action finale sur chaque Client ayant réussi","Job definition persisted":"Définition du travail enregistrée","Persisted remote deployment jobs":"Travaux de déploiement distants enregistrés","Client list truncated":"Liste des Clients tronquée","Multicast network warnings":"Avertissements réseau multicast","Multicast preflight failed":"Échec du contrôle préalable multicast","Execution error":"Erreur d’exécution","Feclora deployment history":"Historique des déploiements Feclora","Repository ID":"ID du dépôt","Server hostname or IPv4 address":"Nom d’hôte ou adresse IPv4 du Serveur","Username":"Nom d’utilisateur","Encrypted SSH private-key credential":"Identifiant de clé privée SSH chiffré","Encrypted pinned SSH known_hosts credential":"Identifiant known_hosts SSH épinglé et chiffré","Encrypted SMB credentials":"Identifiants SMB chiffrés","Port (optional)":"Port (facultatif)","Mount access":"Accès au montage","Credential ID":"ID d’identifiant","Credential type":"Type d’identifiant","Protected source file path":"Chemin du fichier source protégé","Encrypted repository credentials":"Identifiants du dépôt chiffrés","S3 endpoint URL (optional; empty for AWS S3)":"URL du point de terminaison S3 (facultatif ; vide pour AWS S3)","Region":"Région","Bucket":"Bucket","Object prefix":"Préfixe d’objet","Encrypted S3 credential":"Identifiant S3 chiffré","S3 object repositories":"Dépôts d’objets S3","Remote image repositories":"Dépôts d’images distants","Local operation history":"Historique des opérations locales"},
 de: {"Selected Client MAC addresses":"MAC-Adressen der ausgewählten Clients","Server network interface":"Netzwerkschnittstelle des Servers","Administratively scoped multicast group":"Administrativ begrenzte Multicast-Gruppe","UDPcast even portbase":"Gerade UDPcast-Portbasis","Multicast transport limitation":"Einschränkung des Multicast-Transports","Start policy":"Startregel","Minimum READY Clients":"Mindestanzahl READY-Clients","Start deadline (local time)":"Startfrist (Ortszeit)","Final action on each successful Client":"Abschlussaktion für jeden erfolgreichen Client","Job definition persisted":"Auftragsdefinition gespeichert","Persisted remote deployment jobs":"Gespeicherte Remote-Deployment-Aufträge","Client list truncated":"Clientliste gekürzt","Multicast network warnings":"Multicast-Netzwerkwarnungen","Multicast preflight failed":"Multicast-Vorprüfung fehlgeschlagen","Execution error":"Ausführungsfehler","Feclora deployment history":"Feclora-Deployment-Verlauf","Repository ID":"Repository-ID","Server hostname or IPv4 address":"Server-Hostname oder IPv4-Adresse","Username":"Benutzername","Encrypted SSH private-key credential":"Verschlüsselte SSH-Privatschlüssel-Anmeldedaten","Encrypted pinned SSH known_hosts credential":"Verschlüsselte, angeheftete SSH-known_hosts-Anmeldedaten","Encrypted SMB credentials":"Verschlüsselte SMB-Anmeldedaten","Port (optional)":"Port (optional)","Mount access":"Mount-Zugriff","Credential ID":"Anmeldedaten-ID","Credential type":"Anmeldedatentyp","Protected source file path":"Geschützter Quelldateipfad","Encrypted repository credentials":"Verschlüsselte Repository-Anmeldedaten","S3 endpoint URL (optional; empty for AWS S3)":"S3-Endpunkt-URL (optional; leer für AWS S3)","Region":"Region","Bucket":"Bucket","Object prefix":"Objektpräfix","Encrypted S3 credential":"Verschlüsselte S3-Anmeldedaten","S3 object repositories":"S3-Objektrepositories","Remote image repositories":"Remote-Image-Repositories","Local operation history":"Verlauf lokaler Vorgänge"},
 it: {"Selected Client MAC addresses":"Indirizzi MAC dei Client selezionati","Server network interface":"Interfaccia di rete del Server","Administratively scoped multicast group":"Gruppo multicast con ambito amministrativo","UDPcast even portbase":"Porta base pari UDPcast","Multicast transport limitation":"Limite del trasporto multicast","Start policy":"Politica di avvio","Minimum READY Clients":"Numero minimo di Client READY","Start deadline (local time)":"Scadenza di avvio (ora locale)","Final action on each successful Client":"Azione finale per ogni Client riuscito","Job definition persisted":"Definizione del job salvata","Persisted remote deployment jobs":"Job di distribuzione remota salvati","Client list truncated":"Elenco Client troncato","Multicast network warnings":"Avvisi di rete multicast","Multicast preflight failed":"Controllo preliminare multicast non riuscito","Execution error":"Errore di esecuzione","Feclora deployment history":"Cronologia distribuzioni Feclora","Repository ID":"ID repository","Server hostname or IPv4 address":"Nome host o indirizzo IPv4 del Server","Username":"Nome utente","Encrypted SSH private-key credential":"Credenziale della chiave privata SSH cifrata","Encrypted pinned SSH known_hosts credential":"Credenziale known_hosts SSH fissata e cifrata","Encrypted SMB credentials":"Credenziali SMB cifrate","Port (optional)":"Porta (opzionale)","Mount access":"Accesso al mount","Credential ID":"ID credenziale","Credential type":"Tipo credenziale","Protected source file path":"Percorso del file sorgente protetto","Encrypted repository credentials":"Credenziali repository cifrate","S3 endpoint URL (optional; empty for AWS S3)":"URL endpoint S3 (opzionale; vuoto per AWS S3)","Region":"Regione","Bucket":"Bucket","Object prefix":"Prefisso oggetto","Encrypted S3 credential":"Credenziale S3 cifrata","S3 object repositories":"Repository di oggetti S3","Remote image repositories":"Repository immagini remoti","Local operation history":"Cronologia operazioni locali"},
 zh: {"Selected Client MAC addresses":"所选客户端 MAC 地址","Server network interface":"服务器网络接口","Administratively scoped multicast group":"管理范围多播组","UDPcast even portbase":"UDPcast 偶数基端口","Multicast transport limitation":"多播传输限制","Start policy":"启动策略","Minimum READY Clients":"READY 客户端最少数量","Start deadline (local time)":"启动截止时间（本地时间）","Final action on each successful Client":"每个成功客户端的最终操作","Job definition persisted":"任务定义已保存","Persisted remote deployment jobs":"已保存的远程部署任务","Client list truncated":"客户端列表已截断","Multicast network warnings":"多播网络警告","Multicast preflight failed":"多播预检失败","Execution error":"执行错误","Feclora deployment history":"Feclora 部署历史","Repository ID":"存储库 ID","Server hostname or IPv4 address":"服务器主机名或 IPv4 地址","Username":"用户名","Encrypted SSH private-key credential":"已加密的 SSH 私钥凭据","Encrypted pinned SSH known_hosts credential":"已固定并加密的 SSH known_hosts 凭据","Encrypted SMB credentials":"已加密的 SMB 凭据","Port (optional)":"端口（可选）","Mount access":"挂载访问模式","Credential ID":"凭据 ID","Credential type":"凭据类型","Protected source file path":"受保护的源文件路径","Encrypted repository credentials":"已加密的存储库凭据","S3 endpoint URL (optional; empty for AWS S3)":"S3 端点 URL（可选；AWS S3 留空）","Region":"区域","Bucket":"存储桶","Object prefix":"对象前缀","Encrypted S3 credential":"已加密的 S3 凭据","S3 object repositories":"S3 对象存储库","Remote image repositories":"远程映像存储库","Local operation history":"本地操作历史"},
 ja: {"Selected Client MAC addresses":"選択した Client の MAC アドレス","Server network interface":"Server のネットワークインターフェース","Administratively scoped multicast group":"管理スコープのマルチキャストグループ","UDPcast even portbase":"UDPcast の偶数ポートベース","Multicast transport limitation":"マルチキャスト転送の制限","Start policy":"開始ポリシー","Minimum READY Clients":"必要な READY Client の最小数","Start deadline (local time)":"開始期限（ローカル時刻）","Final action on each successful Client":"成功した各 Client の終了アクション","Job definition persisted":"ジョブ定義を保存しました","Persisted remote deployment jobs":"保存済みリモートデプロイジョブ","Client list truncated":"Client リストを省略しました","Multicast network warnings":"マルチキャストネットワークの警告","Multicast preflight failed":"マルチキャスト事前確認に失敗","Execution error":"実行エラー","Feclora deployment history":"Feclora デプロイ履歴","Repository ID":"リポジトリ ID","Server hostname or IPv4 address":"Server のホスト名または IPv4 アドレス","Username":"ユーザー名","Encrypted SSH private-key credential":"暗号化された SSH 秘密鍵資格情報","Encrypted pinned SSH known_hosts credential":"固定済み SSH known_hosts の暗号化資格情報","Encrypted SMB credentials":"暗号化された SMB 資格情報","Port (optional)":"ポート（任意）","Mount access":"マウントアクセス","Credential ID":"資格情報 ID","Credential type":"資格情報の種類","Protected source file path":"保護されたソースファイルのパス","Encrypted repository credentials":"暗号化されたリポジトリ資格情報","S3 endpoint URL (optional; empty for AWS S3)":"S3 エンドポイント URL（任意。AWS S3 では空欄）","Region":"リージョン","Bucket":"バケット","Object prefix":"オブジェクトプレフィックス","Encrypted S3 credential":"暗号化された S3 資格情報","S3 object repositories":"S3 オブジェクトリポジトリ","Remote image repositories":"リモートイメージリポジトリ","Local operation history":"ローカル操作履歴"},
 ru: {"Selected Client MAC addresses":"MAC-адреса выбранных клиентов","Server network interface":"Сетевой интерфейс сервера","Administratively scoped multicast group":"Многоадресная группа административной области","UDPcast even portbase":"Чётная базовая UDPcast-порта","Multicast transport limitation":"Ограничение multicast-транспорта","Start policy":"Политика запуска","Minimum READY Clients":"Минимальное число READY-клиентов","Start deadline (local time)":"Срок запуска (местное время)","Final action on each successful Client":"Действие после успеха на каждом клиенте","Job definition persisted":"Определение задания сохранено","Persisted remote deployment jobs":"Сохранённые задания удалённого развёртывания","Client list truncated":"Список клиентов сокращён","Multicast network warnings":"Предупреждения multicast-сети","Multicast preflight failed":"Предварительная проверка multicast не пройдена","Execution error":"Ошибка выполнения","Feclora deployment history":"История развёртывания Feclora","Repository ID":"ID репозитория","Server hostname or IPv4 address":"Имя узла или IPv4-адрес сервера","Username":"Имя пользователя","Encrypted SSH private-key credential":"Зашифрованные данные закрытого SSH-ключа","Encrypted pinned SSH known_hosts credential":"Зашифрованные закреплённые данные SSH known_hosts","Encrypted SMB credentials":"Зашифрованные учётные данные SMB","Port (optional)":"Порт (необязательно)","Mount access":"Доступ к монтированию","Credential ID":"ID учётных данных","Credential type":"Тип учётных данных","Protected source file path":"Путь к защищённому исходному файлу","Encrypted repository credentials":"Зашифрованные учётные данные репозитория","S3 endpoint URL (optional; empty for AWS S3)":"URL конечной точки S3 (необязательно; для AWS S3 оставить пустым)","Region":"Регион","Bucket":"Bucket","Object prefix":"Префикс объекта","Encrypted S3 credential":"Зашифрованные учётные данные S3","S3 object repositories":"Репозитории объектов S3","Remote image repositories":"Удалённые репозитории образов","Local operation history":"История локальных операций"},
 ar: {"Selected Client MAC addresses":"عناوين MAC للعملاء المحددين","Server network interface":"واجهة شبكة الخادم","Administratively scoped multicast group":"مجموعة بث متعدد ذات نطاق إداري","UDPcast even portbase":"قاعدة منفذ UDPcast زوجية","Multicast transport limitation":"قيود نقل البث المتعدد","Start policy":"سياسة البدء","Minimum READY Clients":"الحد الأدنى من العملاء READY","Start deadline (local time)":"الموعد النهائي للبدء (التوقيت المحلي)","Final action on each successful Client":"الإجراء النهائي لكل عميل ناجح","Job definition persisted":"تم حفظ تعريف المهمة","Persisted remote deployment jobs":"مهام النشر البعيدة المحفوظة","Client list truncated":"تم اقتطاع قائمة العملاء","Multicast network warnings":"تحذيرات شبكة البث المتعدد","Multicast preflight failed":"فشل الفحص المسبق للبث المتعدد","Execution error":"خطأ في التنفيذ","Feclora deployment history":"سجل نشر Feclora","Repository ID":"معرّف المستودع","Server hostname or IPv4 address":"اسم مضيف الخادم أو عنوان IPv4","Username":"اسم المستخدم","Encrypted SSH private-key credential":"بيانات اعتماد مفتاح SSH الخاص المشفرة","Encrypted pinned SSH known_hosts credential":"بيانات اعتماد known_hosts المثبتة والمشفرة","Encrypted SMB credentials":"بيانات اعتماد SMB المشفرة","Port (optional)":"المنفذ (اختياري)","Mount access":"صلاحية التحميل","Credential ID":"معرّف بيانات الاعتماد","Credential type":"نوع بيانات الاعتماد","Protected source file path":"مسار ملف المصدر المحمي","Encrypted repository credentials":"بيانات اعتماد المستودع المشفرة","S3 endpoint URL (optional; empty for AWS S3)":"عنوان نقطة نهاية S3 (اختياري؛ اتركه فارغاً لـ AWS S3)","Region":"المنطقة","Bucket":"الحاوية","Object prefix":"بادئة الكائن","Encrypted S3 credential":"بيانات اعتماد S3 المشفرة","S3 object repositories":"مستودعات كائنات S3","Remote image repositories":"مستودعات الصور البعيدة","Local operation history":"سجل العمليات المحلية"},
 tr: {"Selected Client MAC addresses":"Seçili İstemcilerin MAC adresleri","Server network interface":"Sunucu ağ arayüzü","Administratively scoped multicast group":"Yönetim kapsamlı çok noktaya yayın grubu","UDPcast even portbase":"UDPcast çift taban bağlantı noktası","Multicast transport limitation":"Çok noktaya yayın aktarım sınırlaması","Start policy":"Başlatma ilkesi","Minimum READY Clients":"En az READY İstemci sayısı","Start deadline (local time)":"Başlatma son tarihi (yerel saat)","Final action on each successful Client":"Başarılı her İstemci için son işlem","Job definition persisted":"İş tanımı kaydedildi","Persisted remote deployment jobs":"Kaydedilmiş uzak dağıtım işleri","Client list truncated":"İstemci listesi kısaltıldı","Multicast network warnings":"Çok noktaya yayın ağ uyarıları","Multicast preflight failed":"Çok noktaya yayın ön denetimi başarısız","Execution error":"Yürütme hatası","Feclora deployment history":"Feclora dağıtım geçmişi","Repository ID":"Depo kimliği","Server hostname or IPv4 address":"Sunucu ana bilgisayar adı veya IPv4 adresi","Username":"Kullanıcı adı","Encrypted SSH private-key credential":"Şifrelenmiş SSH özel anahtar kimlik bilgisi","Encrypted pinned SSH known_hosts credential":"Sabitlenmiş şifreli SSH known_hosts kimlik bilgisi","Encrypted SMB credentials":"Şifrelenmiş SMB kimlik bilgileri","Port (optional)":"Bağlantı noktası (isteğe bağlı)","Mount access":"Bağlama erişimi","Credential ID":"Kimlik bilgisi kimliği","Credential type":"Kimlik bilgisi türü","Protected source file path":"Korunan kaynak dosya yolu","Encrypted repository credentials":"Şifrelenmiş depo kimlik bilgileri","S3 endpoint URL (optional; empty for AWS S3)":"S3 uç nokta URL'si (isteğe bağlı; AWS S3 için boş bırakın)","Region":"Bölge","Bucket":"Bucket","Object prefix":"Nesne öneki","Encrypted S3 credential":"Şifrelenmiş S3 kimlik bilgisi","S3 object repositories":"S3 nesne depoları","Remote image repositories":"Uzak görüntü depoları","Local operation history":"Yerel işlem geçmişi"}
};
for (const [language, values] of Object.entries(APP_UI_TEXT_REMOTE)) {
  Object.assign(DICTS[language], values);
}

const APP_UI_TEXT_ADMIN = {
 es: {"Export latest 100 operations as JSON":"Exportar las últimas 100 operaciones como JSON","Destination may be partially written.":"El destino puede haberse escrito parcialmente.","Initialize deployment Server identity":"Inicializar la identidad del Servidor de despliegue","Initialize Server identity":"Inicializar identidad del Servidor","Rotate Server TLS keypair":"Rotar el par de claves TLS del Servidor","Renew Server TLS certificate":"Renovar el certificado TLS del Servidor","Renew Server certificate":"Renovar certificado del Servidor","Run PXE preflight":"Ejecutar comprobación previa de PXE","Stop PXE services and restore firewall":"Detener servicios PXE y restaurar el cortafuegos","Publish unattended PXE answer":"Publicar respuesta PXE desatendida","Validate and publish answer":"Validar y publicar respuesta","Revoke published answer":"Revocar respuesta publicada","Unlock encrypted PXE restore":"Desbloquear restauración PXE cifrada","Activate PXE services":"Activar servicios PXE","Connect and wait for Server authorization":"Conectar y esperar la autorización del Servidor","Client jobs":"Trabajos del Cliente","Client enrollment required":"Se requiere registrar el Cliente","Remote job UUID":"UUID del trabajo remoto","Local multicast receive interface (also used for the Server connection)":"Interfaz local de recepción multicast (también usada para conectar con el Servidor)","Multicast network requirements":"Requisitos de red multicast","Capture compression":"Compresión de captura","Protect this image (optional)":"Proteger esta imagen (opcional)","Type the exact local authorization phrase":"Escribe exactamente la frase de autorización local","Local target confirmation":"Confirmación del destino local","Multicast switch checks":"Comprobaciones multicast del conmutador","Client service interrupted":"Servicio del Cliente interrumpido","Feclora services":"Servicios de Feclora","Image security material":"Material de seguridad de imágenes"},
 ca: {"Export latest 100 operations as JSON":"Exporta les darreres 100 operacions com a JSON","Destination may be partially written.":"És possible que la destinació s'hagi escrit parcialment.","Initialize deployment Server identity":"Inicialitza la identitat del Servidor de desplegament","Initialize Server identity":"Inicialitza la identitat del Servidor","Rotate Server TLS keypair":"Rota el parell de claus TLS del Servidor","Renew Server TLS certificate":"Renova el certificat TLS del Servidor","Renew Server certificate":"Renova el certificat del Servidor","Run PXE preflight":"Executa la comprovació prèvia de PXE","Stop PXE services and restore firewall":"Atura els serveis PXE i restaura el tallafoc","Publish unattended PXE answer":"Publica la resposta PXE desatesa","Validate and publish answer":"Valida i publica la resposta","Revoke published answer":"Revoca la resposta publicada","Unlock encrypted PXE restore":"Desbloqueja la restauració PXE xifrada","Activate PXE services":"Activa els serveis PXE","Connect and wait for Server authorization":"Connecta i espera l'autorització del Servidor","Client jobs":"Tasques del Client","Client enrollment required":"Cal registrar el Client","Remote job UUID":"UUID de la tasca remota","Local multicast receive interface (also used for the Server connection)":"Interfície local de recepció multicast (també s'utilitza per connectar amb el Servidor)","Multicast network requirements":"Requisits de xarxa multicast","Capture compression":"Compressió de captura","Protect this image (optional)":"Protegeix aquesta imatge (opcional)","Type the exact local authorization phrase":"Escriu exactament la frase d'autorització local","Local target confirmation":"Confirmació de la destinació local","Multicast switch checks":"Comprovacions multicast del commutador","Client service interrupted":"Servei del Client interromput","Feclora services":"Serveis de Feclora","Image security material":"Material de seguretat de les imatges"},
 gl: {"Export latest 100 operations as JSON":"Exportar as últimas 100 operacións como JSON","Destination may be partially written.":"É posible que o destino estea escrito parcialmente.","Initialize deployment Server identity":"Inicializar a identidade do Servidor de despregamento","Initialize Server identity":"Inicializar a identidade do Servidor","Rotate Server TLS keypair":"Rotar o par de claves TLS do Servidor","Renew Server TLS certificate":"Renovar o certificado TLS do Servidor","Renew Server certificate":"Renovar o certificado do Servidor","Run PXE preflight":"Executar a comprobación previa de PXE","Stop PXE services and restore firewall":"Deter os servizos PXE e restaurar o firewall","Publish unattended PXE answer":"Publicar a resposta PXE desatendida","Validate and publish answer":"Validar e publicar a resposta","Revoke published answer":"Revogar a resposta publicada","Unlock encrypted PXE restore":"Desbloquear a restauración PXE cifrada","Activate PXE services":"Activar os servizos PXE","Connect and wait for Server authorization":"Conectar e agardar pola autorización do Servidor","Client jobs":"Tarefas do Cliente","Client enrollment required":"Cómpre rexistrar o Cliente","Remote job UUID":"UUID da tarefa remota","Local multicast receive interface (also used for the Server connection)":"Interface local de recepción multicast (tamén usada para conectar co Servidor)","Multicast network requirements":"Requisitos da rede multicast","Capture compression":"Compresión da captura","Protect this image (optional)":"Protexer esta imaxe (opcional)","Type the exact local authorization phrase":"Escribe exactamente a frase de autorización local","Local target confirmation":"Confirmación do destino local","Multicast switch checks":"Comprobacións multicast do conmutador","Client service interrupted":"Servizo do Cliente interrompido","Feclora services":"Servizos de Feclora","Image security material":"Material de seguridade das imaxes"},
 eu: {"Export latest 100 operations as JSON":"Esportatu azken 100 eragiketak JSON gisa","Destination may be partially written.":"Baliteke helburuan datuak partzialki idatzi izana.","Initialize deployment Server identity":"Hasieratu inplementazio-zerbitzariaren identitatea","Initialize Server identity":"Hasieratu zerbitzariaren identitatea","Rotate Server TLS keypair":"Biratu zerbitzariaren TLS gako-parea","Renew Server TLS certificate":"Berritu zerbitzariaren TLS ziurtagiria","Renew Server certificate":"Berritu zerbitzariaren ziurtagiria","Run PXE preflight":"Exekutatu PXE aurre-egiaztapena","Stop PXE services and restore firewall":"Gelditu PXE zerbitzuak eta leheneratu suebakia","Publish unattended PXE answer":"Argitaratu PXE erantzun automatikoa","Validate and publish answer":"Balioztatu eta argitaratu erantzuna","Revoke published answer":"Ezeztatu argitaratutako erantzuna","Unlock encrypted PXE restore":"Desblokeatu enkriptatutako PXE leheneratzea","Activate PXE services":"Aktibatu PXE zerbitzuak","Connect and wait for Server authorization":"Konektatu eta itxaron zerbitzariaren baimenari","Client jobs":"Bezeroaren lanak","Client enrollment required":"Bezeroa erregistratu behar da","Remote job UUID":"Urruneko lanaren UUIDa","Local multicast receive interface (also used for the Server connection)":"Multicast jasotzeko interfaze lokala (zerbitzariarekin konektatzeko ere erabiltzen da)","Multicast network requirements":"Multicast sarearen eskakizunak","Capture compression":"Harrapaketaren konpresioa","Protect this image (optional)":"Babestu irudi hau (aukerakoa)","Type the exact local authorization phrase":"Idatzi zehazki tokiko baimen-esaldia","Local target confirmation":"Tokiko helburuaren berrespena","Multicast switch checks":"Multicast kommutadorearen egiaztapenak","Client service interrupted":"Bezeroaren zerbitzua eten da","Feclora services":"Feclora zerbitzuak","Image security material":"Irudien segurtasun-materiala"},
 pt: {"Export latest 100 operations as JSON":"Exportar as 100 operações mais recentes em JSON","Destination may be partially written.":"O destino pode ter sido escrito parcialmente.","Initialize deployment Server identity":"Inicializar a identidade do Servidor de implementação","Initialize Server identity":"Inicializar a identidade do Servidor","Rotate Server TLS keypair":"Rodar o par de chaves TLS do Servidor","Renew Server TLS certificate":"Renovar o certificado TLS do Servidor","Renew Server certificate":"Renovar o certificado do Servidor","Run PXE preflight":"Executar pré-verificação PXE","Stop PXE services and restore firewall":"Parar os serviços PXE e restaurar a firewall","Publish unattended PXE answer":"Publicar resposta PXE não assistida","Validate and publish answer":"Validar e publicar resposta","Revoke published answer":"Revogar resposta publicada","Unlock encrypted PXE restore":"Desbloquear restauro PXE encriptado","Activate PXE services":"Ativar serviços PXE","Connect and wait for Server authorization":"Ligar e aguardar autorização do Servidor","Client jobs":"Tarefas do Cliente","Client enrollment required":"É necessário registar o Cliente","Remote job UUID":"UUID da tarefa remota","Local multicast receive interface (also used for the Server connection)":"Interface local de receção multicast (também usada para ligar ao Servidor)","Multicast network requirements":"Requisitos da rede multicast","Capture compression":"Compressão da captura","Protect this image (optional)":"Proteger esta imagem (opcional)","Type the exact local authorization phrase":"Escreva exatamente a frase de autorização local","Local target confirmation":"Confirmação do destino local","Multicast switch checks":"Verificações multicast do comutador","Client service interrupted":"Serviço do Cliente interrompido","Feclora services":"Serviços Feclora","Image security material":"Material de segurança das imagens"},
 fr: {"Export latest 100 operations as JSON":"Exporter les 100 dernières opérations au format JSON","Destination may be partially written.":"La destination peut avoir été partiellement écrite.","Initialize deployment Server identity":"Initialiser l’identité du Serveur de déploiement","Initialize Server identity":"Initialiser l’identité du Serveur","Rotate Server TLS keypair":"Faire pivoter la paire de clés TLS du Serveur","Renew Server TLS certificate":"Renouveler le certificat TLS du Serveur","Renew Server certificate":"Renouveler le certificat du Serveur","Run PXE preflight":"Exécuter le contrôle préalable PXE","Stop PXE services and restore firewall":"Arrêter les services PXE et restaurer le pare-feu","Publish unattended PXE answer":"Publier la réponse PXE sans surveillance","Validate and publish answer":"Valider et publier la réponse","Revoke published answer":"Révoquer la réponse publiée","Unlock encrypted PXE restore":"Déverrouiller la restauration PXE chiffrée","Activate PXE services":"Activer les services PXE","Connect and wait for Server authorization":"Se connecter et attendre l’autorisation du Serveur","Client jobs":"Travaux du Client","Client enrollment required":"Enregistrement du Client requis","Remote job UUID":"UUID du travail distant","Local multicast receive interface (also used for the Server connection)":"Interface locale de réception multicast (également utilisée pour la connexion au Serveur)","Multicast network requirements":"Exigences réseau multicast","Capture compression":"Compression de capture","Protect this image (optional)":"Protéger cette image (facultatif)","Type the exact local authorization phrase":"Saisissez exactement la phrase d’autorisation locale","Local target confirmation":"Confirmation de la cible locale","Multicast switch checks":"Vérifications multicast du commutateur","Client service interrupted":"Service Client interrompu","Feclora services":"Services Feclora","Image security material":"Matériel de sécurité des images"},
 de: {"Export latest 100 operations as JSON":"Letzte 100 Vorgänge als JSON exportieren","Destination may be partially written.":"Das Ziel wurde möglicherweise teilweise beschrieben.","Initialize deployment Server identity":"Deployment-Serveridentität initialisieren","Initialize Server identity":"Serveridentität initialisieren","Rotate Server TLS keypair":"Server-TLS-Schlüsselpaar rotieren","Renew Server TLS certificate":"Server-TLS-Zertifikat erneuern","Renew Server certificate":"Serverzertifikat erneuern","Run PXE preflight":"PXE-Vorprüfung ausführen","Stop PXE services and restore firewall":"PXE-Dienste stoppen und Firewall wiederherstellen","Publish unattended PXE answer":"Unbeaufsichtigte PXE-Antwort veröffentlichen","Validate and publish answer":"Antwort prüfen und veröffentlichen","Revoke published answer":"Veröffentlichte Antwort widerrufen","Unlock encrypted PXE restore":"Verschlüsselte PXE-Wiederherstellung entsperren","Activate PXE services":"PXE-Dienste aktivieren","Connect and wait for Server authorization":"Verbinden und auf Serverfreigabe warten","Client jobs":"Client-Aufträge","Client enrollment required":"Client-Registrierung erforderlich","Remote job UUID":"Remote-Auftrags-UUID","Local multicast receive interface (also used for the Server connection)":"Lokale Multicast-Empfangsschnittstelle (auch für die Serververbindung)","Multicast network requirements":"Multicast-Netzwerkanforderungen","Capture compression":"Aufnahme-Komprimierung","Protect this image (optional)":"Dieses Image schützen (optional)","Type the exact local authorization phrase":"Geben Sie die lokale Freigabephrase exakt ein","Local target confirmation":"Lokale Zielbestätigung","Multicast switch checks":"Multicast-Switch-Prüfungen","Client service interrupted":"Client-Dienst unterbrochen","Feclora services":"Feclora-Dienste","Image security material":"Image-Sicherheitsmaterial"},
 it: {"Export latest 100 operations as JSON":"Esporta le ultime 100 operazioni in JSON","Destination may be partially written.":"La destinazione potrebbe essere stata scritta parzialmente.","Initialize deployment Server identity":"Inizializza l'identità del Server di distribuzione","Initialize Server identity":"Inizializza l'identità del Server","Rotate Server TLS keypair":"Ruota la coppia di chiavi TLS del Server","Renew Server TLS certificate":"Rinnova il certificato TLS del Server","Renew Server certificate":"Rinnova il certificato del Server","Run PXE preflight":"Esegui il controllo preliminare PXE","Stop PXE services and restore firewall":"Arresta i servizi PXE e ripristina il firewall","Publish unattended PXE answer":"Pubblica la risposta PXE non presidiata","Validate and publish answer":"Convalida e pubblica la risposta","Revoke published answer":"Revoca la risposta pubblicata","Unlock encrypted PXE restore":"Sblocca il ripristino PXE cifrato","Activate PXE services":"Attiva i servizi PXE","Connect and wait for Server authorization":"Connettiti e attendi l'autorizzazione del Server","Client jobs":"Job Client","Client enrollment required":"Registrazione Client richiesta","Remote job UUID":"UUID del job remoto","Local multicast receive interface (also used for the Server connection)":"Interfaccia locale di ricezione multicast (usata anche per la connessione al Server)","Multicast network requirements":"Requisiti di rete multicast","Capture compression":"Compressione acquisizione","Protect this image (optional)":"Proteggi questa immagine (opzionale)","Type the exact local authorization phrase":"Digita esattamente la frase di autorizzazione locale","Local target confirmation":"Conferma destinazione locale","Multicast switch checks":"Controlli multicast dello switch","Client service interrupted":"Servizio Client interrotto","Feclora services":"Servizi Feclora","Image security material":"Materiale di sicurezza delle immagini"},
 zh: {"Export latest 100 operations as JSON":"将最近 100 项操作导出为 JSON","Destination may be partially written.":"目标磁盘可能已被部分写入。","Initialize deployment Server identity":"初始化部署服务器身份","Initialize Server identity":"初始化服务器身份","Rotate Server TLS keypair":"轮换服务器 TLS 密钥对","Renew Server TLS certificate":"续订服务器 TLS 证书","Renew Server certificate":"续订服务器证书","Run PXE preflight":"运行 PXE 预检","Stop PXE services and restore firewall":"停止 PXE 服务并恢复防火墙","Publish unattended PXE answer":"发布无人值守 PXE 答案","Validate and publish answer":"验证并发布答案","Revoke published answer":"撤销已发布的答案","Unlock encrypted PXE restore":"解锁加密的 PXE 恢复","Activate PXE services":"启用 PXE 服务","Connect and wait for Server authorization":"连接并等待服务器授权","Client jobs":"客户端任务","Client enrollment required":"需要注册客户端","Remote job UUID":"远程任务 UUID","Local multicast receive interface (also used for the Server connection)":"本地多播接收接口（也用于连接服务器）","Multicast network requirements":"多播网络要求","Capture compression":"采集压缩","Protect this image (optional)":"保护此映像（可选）","Type the exact local authorization phrase":"准确输入本地授权短语","Local target confirmation":"本地目标确认","Multicast switch checks":"多播交换机检查","Client service interrupted":"客户端服务中断","Feclora services":"Feclora 服务","Image security material":"映像安全材料"},
 ja: {"Export latest 100 operations as JSON":"最新 100 件の操作を JSON としてエクスポート","Destination may be partially written.":"宛先には一部のデータが書き込まれている可能性があります。","Initialize deployment Server identity":"デプロイ Server の ID を初期化","Initialize Server identity":"Server ID を初期化","Rotate Server TLS keypair":"Server TLS キーペアをローテーション","Renew Server TLS certificate":"Server TLS 証明書を更新","Renew Server certificate":"Server 証明書を更新","Run PXE preflight":"PXE の事前確認を実行","Stop PXE services and restore firewall":"PXE サービスを停止してファイアウォールを復元","Publish unattended PXE answer":"無人 PXE 応答を公開","Validate and publish answer":"応答を検証して公開","Revoke published answer":"公開済み応答を取り消す","Unlock encrypted PXE restore":"暗号化された PXE 復元を解除","Activate PXE services":"PXE サービスを有効化","Connect and wait for Server authorization":"接続して Server の承認を待つ","Client jobs":"Client ジョブ","Client enrollment required":"Client の登録が必要","Remote job UUID":"リモートジョブ UUID","Local multicast receive interface (also used for the Server connection)":"ローカルのマルチキャスト受信インターフェース（Server 接続にも使用）","Multicast network requirements":"マルチキャストネットワーク要件","Capture compression":"取得時の圧縮","Protect this image (optional)":"このイメージを保護（任意）","Type the exact local authorization phrase":"ローカル承認フレーズを正確に入力","Local target confirmation":"ローカル対象の確認","Multicast switch checks":"マルチキャストスイッチの確認","Client service interrupted":"Client サービスが中断されました","Feclora services":"Feclora サービス","Image security material":"イメージセキュリティ情報"},
 ru: {"Export latest 100 operations as JSON":"Экспортировать последние 100 операций в JSON","Destination may be partially written.":"Возможно, целевой диск записан частично.","Initialize deployment Server identity":"Инициализировать идентификатор сервера развёртывания","Initialize Server identity":"Инициализировать идентификатор сервера","Rotate Server TLS keypair":"Сменить пару ключей TLS сервера","Renew Server TLS certificate":"Обновить сертификат TLS сервера","Renew Server certificate":"Обновить сертификат сервера","Run PXE preflight":"Выполнить предварительную проверку PXE","Stop PXE services and restore firewall":"Остановить службы PXE и восстановить брандмауэр","Publish unattended PXE answer":"Опубликовать ответ PXE для автоматического режима","Validate and publish answer":"Проверить и опубликовать ответ","Revoke published answer":"Отозвать опубликованный ответ","Unlock encrypted PXE restore":"Разблокировать зашифрованное восстановление PXE","Activate PXE services":"Активировать службы PXE","Connect and wait for Server authorization":"Подключиться и ждать разрешения сервера","Client jobs":"Задания клиента","Client enrollment required":"Требуется регистрация клиента","Remote job UUID":"UUID удалённого задания","Local multicast receive interface (also used for the Server connection)":"Локальный интерфейс приёма multicast (также используется для подключения к серверу)","Multicast network requirements":"Требования multicast-сети","Capture compression":"Сжатие при захвате","Protect this image (optional)":"Защитить этот образ (необязательно)","Type the exact local authorization phrase":"Введите точную локальную фразу подтверждения","Local target confirmation":"Подтверждение локальной цели","Multicast switch checks":"Проверки multicast-коммутатора","Client service interrupted":"Служба клиента прервана","Feclora services":"Службы Feclora","Image security material":"Материалы безопасности образов"},
 ar: {"Export latest 100 operations as JSON":"تصدير آخر 100 عملية بتنسيق JSON","Destination may be partially written.":"قد تكون الوجهة قد كُتبت جزئياً.","Initialize deployment Server identity":"تهيئة هوية خادم النشر","Initialize Server identity":"تهيئة هوية الخادم","Rotate Server TLS keypair":"تدوير زوج مفاتيح TLS للخادم","Renew Server TLS certificate":"تجديد شهادة TLS للخادم","Renew Server certificate":"تجديد شهادة الخادم","Run PXE preflight":"تشغيل الفحص المسبق لـ PXE","Stop PXE services and restore firewall":"إيقاف خدمات PXE واستعادة جدار الحماية","Publish unattended PXE answer":"نشر إجابة PXE غير التفاعلية","Validate and publish answer":"التحقق من الإجابة ونشرها","Revoke published answer":"إلغاء الإجابة المنشورة","Unlock encrypted PXE restore":"إلغاء قفل استعادة PXE المشفرة","Activate PXE services":"تفعيل خدمات PXE","Connect and wait for Server authorization":"الاتصال وانتظار تفويض الخادم","Client jobs":"مهام العميل","Client enrollment required":"يلزم تسجيل العميل","Remote job UUID":"UUID المهمة البعيدة","Local multicast receive interface (also used for the Server connection)":"واجهة استقبال البث المتعدد المحلية (تُستخدم أيضاً لاتصال الخادم)","Multicast network requirements":"متطلبات شبكة البث المتعدد","Capture compression":"ضغط الالتقاط","Protect this image (optional)":"حماية هذه الصورة (اختياري)","Type the exact local authorization phrase":"اكتب عبارة التفويض المحلية تماماً","Local target confirmation":"تأكيد الهدف المحلي","Multicast switch checks":"فحوصات محول البث المتعدد","Client service interrupted":"انقطعت خدمة العميل","Feclora services":"خدمات Feclora","Image security material":"مواد أمان الصور"},
 tr: {"Export latest 100 operations as JSON":"Son 100 işlemi JSON olarak dışa aktar","Destination may be partially written.":"Hedef kısmen yazılmış olabilir.","Initialize deployment Server identity":"Dağıtım Sunucusu kimliğini başlat","Initialize Server identity":"Sunucu kimliğini başlat","Rotate Server TLS keypair":"Sunucu TLS anahtar çiftini döndür","Renew Server TLS certificate":"Sunucu TLS sertifikasını yenile","Renew Server certificate":"Sunucu sertifikasını yenile","Run PXE preflight":"PXE ön denetimini çalıştır","Stop PXE services and restore firewall":"PXE hizmetlerini durdur ve güvenlik duvarını geri yükle","Publish unattended PXE answer":"Gözetimsiz PXE yanıtını yayımla","Validate and publish answer":"Yanıtı doğrula ve yayımla","Revoke published answer":"Yayımlanan yanıtı iptal et","Unlock encrypted PXE restore":"Şifrelenmiş PXE geri yüklemesinin kilidini aç","Activate PXE services":"PXE hizmetlerini etkinleştir","Connect and wait for Server authorization":"Bağlan ve Sunucu yetkilendirmesini bekle","Client jobs":"İstemci işleri","Client enrollment required":"İstemci kaydı gerekli","Remote job UUID":"Uzak iş UUID'si","Local multicast receive interface (also used for the Server connection)":"Yerel çok noktaya yayın alım arayüzü (Sunucu bağlantısı için de kullanılır)","Multicast network requirements":"Çok noktaya yayın ağ gereksinimleri","Capture compression":"Yakalama sıkıştırması","Protect this image (optional)":"Bu görüntüyü koru (isteğe bağlı)","Type the exact local authorization phrase":"Yerel yetkilendirme ifadesini aynen yazın","Local target confirmation":"Yerel hedef onayı","Multicast switch checks":"Çok noktaya yayın anahtarı denetimleri","Client service interrupted":"İstemci hizmeti kesintiye uğradı","Feclora services":"Feclora hizmetleri","Image security material":"Görüntü güvenlik malzemesi"}
};
for (const [language, values] of Object.entries(APP_UI_TEXT_ADMIN)) {
  Object.assign(DICTS[language], values);
}
const APP_UI_TEXT_MISC = {
  "es": {
    "Capture whole disks from Clients to Server": "Capturar discos completos de Clientes al Servidor",
    "Review required": "Revisión necesaria",
    "Select imported known_hosts": "Seleccionar known_hosts importado",
    "Select imported SMB credential": "Seleccionar credencial SMB importada",
    "Cancel edit": "Cancelar edición",
    "SSH known_hosts": "known_hosts de SSH",
    "SMB credentials": "Credenciales SMB",
    "Import and encrypt credential": "Importar y cifrar credencial",
    "Encrypted reference": "Referencia cifrada",
    "Action": "Acción",
    "No encrypted credentials imported.": "No se han importado credenciales cifradas.",
    "Check mount identity": "Comprobar identidad del montaje",
    "Management connectivity protection": "Protección de la conectividad de gestión",
    "Apply and verify network configuration": "Aplicar y verificar la configuración de red",
    "Select an interface/address…": "Seleccionar interfaz/dirección…",
    "No eligible IPv4 interface found": "No se encontró una interfaz IPv4 válida",
    "Existing DHCP server detected": "Se detectó un servidor DHCP existente",
    "Server configuration exists": "Existe configuración del Servidor",
    "Client authentication disabled": "Autenticación de Clientes desactivada",
    "New Server private key; existing CA retained": "Nueva clave privada del Servidor; se conserva la CA existente",
    "Submit passphrase to this Live client": "Enviar la frase de paso a este cliente Live",
    "Passphrase submitted": "Frase de paso enviada",
    "PXE preflight passed": "Comprobación previa de PXE superada",
    "Network topology warning": "Advertencia de topología de red",
    "PXE services active": "Servicios PXE activos",
    "PXE runtime needs inspection": "El entorno PXE requiere inspección",
    "Preflight only": "Solo comprobación previa",
    "Client service status": "Estado del servicio del Cliente",
    "Refresh Client status": "Actualizar estado del Cliente",
    "Server deployment configuration": "Configuración de despliegue del Servidor",
    "Client deployment configuration": "Configuración de despliegue del Cliente",
    "Server setup": "Configuración del Servidor",
    "Server TLS keypair rotated": "Par de claves TLS del Servidor rotado",
    "Existing CA and private key will be retained": "Se conservarán la CA y la clave privada existentes",
    "Server certificate renewed": "Certificado del Servidor renovado",
    "DHCP mode": "Modo DHCP",
    "Authoritative DHCP can disrupt an existing network": "El DHCP autoritativo puede interrumpir una red existente",
    "DHCP pool start": "Inicio del rango DHCP",
    "DHCP pool end": "Fin del rango DHCP",
    "Lease duration": "Duración de la concesión",
    "DNS server (optional)": "Servidor DNS (opcional)",
    "HTTP boot asset port": "Puerto de recursos de arranque HTTP",
    "Maximum distinct PXE clients": "Número máximo de Clientes distintos",
    "Maximum PXE serving time (seconds)": "Tiempo máximo de servicio PXE (segundos)",
    "PXE runtime is configured": "El entorno PXE está configurado",
    "Destructive operation guard": "Protección contra operaciones destructivas",
    "Prewritten answer file (JSON)": "Archivo de respuesta preescrito (JSON)",
    "Answer published": "Respuesta publicada",
    "age symmetric passphrase": "Contraseña simétrica de age",
    "Server host override": "Anfitrión del Servidor alternativo",
    "Use enrolled Server host": "Usar el anfitrión del Servidor registrado"
  },
  "ca": {
    "Capture whole disks from Clients to Server": "Captura discs sencers dels Clients al Servidor",
    "Review required": "Cal revisar",
    "Select imported known_hosts": "Selecciona els known_hosts importats",
    "Select imported SMB credential": "Selecciona la credencial SMB importada",
    "Cancel edit": "Cancel·la l'edició",
    "SSH known_hosts": "known_hosts d'SSH",
    "SMB credentials": "Credencials SMB",
    "Import and encrypt credential": "Importa i xifra la credencial",
    "Encrypted reference": "Referència xifrada",
    "Action": "Acció",
    "No encrypted credentials imported.": "No s'ha importat cap credencial xifrada.",
    "Check mount identity": "Comprova la identitat del muntatge",
    "Management connectivity protection": "Protecció de la connectivitat d'administració",
    "Apply and verify network configuration": "Aplica i verifica la configuració de xarxa",
    "Select an interface/address…": "Selecciona una interfície/adreça…",
    "No eligible IPv4 interface found": "No s'ha trobat cap interfície IPv4 apta",
    "Existing DHCP server detected": "S'ha detectat un servidor DHCP existent",
    "Server configuration exists": "La configuració del Servidor ja existeix",
    "Client authentication disabled": "Autenticació dels Clients desactivada",
    "New Server private key; existing CA retained": "Clau privada nova del Servidor; es conserva la CA existent",
    "Submit passphrase to this Live client": "Envia la frase de pas a aquest Client Live",
    "Passphrase submitted": "Frase de pas enviada",
    "PXE preflight passed": "Comprovació prèvia de PXE superada",
    "Network topology warning": "Avís de topologia de xarxa",
    "PXE services active": "Serveis PXE actius",
    "PXE runtime needs inspection": "El temps d'execució PXE requereix inspecció",
    "Preflight only": "Només comprovació prèvia",
    "Client service status": "Estat del servei del Client",
    "Refresh Client status": "Actualitza l'estat del Client",
    "Server deployment configuration": "Configuració de desplegament del Servidor",
    "Client deployment configuration": "Configuració de desplegament del Client",
    "Server setup": "Configuració del Servidor",
    "Server TLS keypair rotated": "Parell de claus TLS del Servidor rotat",
    "Existing CA and private key will be retained": "Es conservaran la CA i la clau privada existents",
    "Server certificate renewed": "Certificat del Servidor renovat",
    "DHCP mode": "Mode DHCP",
    "Authoritative DHCP can disrupt an existing network": "El DHCP autoritatiu pot interrompre una xarxa existent",
    "DHCP pool start": "Inici del rang DHCP",
    "DHCP pool end": "Final del rang DHCP",
    "Lease duration": "Durada de la concessió",
    "DNS server (optional)": "Servidor DNS (opcional)",
    "HTTP boot asset port": "Port dels recursos d'arrencada HTTP",
    "Maximum distinct PXE clients": "Nombre màxim de Clients diferents",
    "Maximum PXE serving time (seconds)": "Temps màxim de servei PXE (segons)",
    "PXE runtime is configured": "L'entorn PXE està configurat",
    "Destructive operation guard": "Protecció contra operacions destructives",
    "Prewritten answer file (JSON)": "Fitxer de resposta preescrit (JSON)",
    "Answer published": "Resposta publicada",
    "age symmetric passphrase": "Contrasenya simètrica d'age",
    "Server host override": "Amfitrió alternatiu del Servidor",
    "Use enrolled Server host": "Fes servir l'amfitrió del Servidor registrat"
  },
  "gl": {
    "Capture whole disks from Clients to Server": "Capturar discos completos dos Clientes ao Servidor",
    "Review required": "Cómpre revisar",
    "Select imported known_hosts": "Seleccionar known_hosts importado",
    "Select imported SMB credential": "Seleccionar credencial SMB importada",
    "Cancel edit": "Cancelar edición",
    "SSH known_hosts": "known_hosts de SSH",
    "SMB credentials": "Credenciais SMB",
    "Import and encrypt credential": "Importar e cifrar credencial",
    "Encrypted reference": "Referencia cifrada",
    "Action": "Acción",
    "No encrypted credentials imported.": "Non se importaron credenciais cifradas.",
    "Check mount identity": "Comprobar identidade da montaxe",
    "Management connectivity protection": "Protección da conectividade de administración",
    "Apply and verify network configuration": "Aplicar e verificar a configuración de rede",
    "Select an interface/address…": "Seleccionar interface/enderezo…",
    "No eligible IPv4 interface found": "Non se atopou unha interface IPv4 válida",
    "Existing DHCP server detected": "Detectouse un servidor DHCP existente",
    "Server configuration exists": "Existe configuración do Servidor",
    "Client authentication disabled": "Autenticación dos Clientes desactivada",
    "New Server private key; existing CA retained": "Nova clave privada do Servidor; consérvase a CA existente",
    "Submit passphrase to this Live client": "Enviar a frase de paso a este Cliente Live",
    "Passphrase submitted": "Frase de paso enviada",
    "PXE preflight passed": "Comprobación previa de PXE superada",
    "Network topology warning": "Aviso de topoloxía de rede",
    "PXE services active": "Servizos PXE activos",
    "PXE runtime needs inspection": "O contorno PXE require inspección",
    "Preflight only": "Só comprobación previa",
    "Client service status": "Estado do servizo do Cliente",
    "Refresh Client status": "Actualizar estado do Cliente",
    "Server deployment configuration": "Configuración de despregamento do Servidor",
    "Client deployment configuration": "Configuración de despregamento do Cliente",
    "Server setup": "Configuración do Servidor",
    "Server TLS keypair rotated": "Par de claves TLS do Servidor rotado",
    "Existing CA and private key will be retained": "Conservaranse a CA e a clave privada existentes",
    "Server certificate renewed": "Certificado do Servidor renovado",
    "DHCP mode": "Modo DHCP",
    "Authoritative DHCP can disrupt an existing network": "O DHCP autoritativo pode interromper unha rede existente",
    "DHCP pool start": "Inicio do rango DHCP",
    "DHCP pool end": "Fin do rango DHCP",
    "Lease duration": "Duración da concesión",
    "DNS server (optional)": "Servidor DNS (opcional)",
    "HTTP boot asset port": "Porto dos recursos de arranque HTTP",
    "Maximum distinct PXE clients": "Número máximo de Clientes distintos",
    "Maximum PXE serving time (seconds)": "Tempo máximo de servizo PXE (segundos)",
    "PXE runtime is configured": "O contorno PXE está configurado",
    "Destructive operation guard": "Protección contra operacións destrutivas",
    "Prewritten answer file (JSON)": "Ficheiro de resposta preescrito (JSON)",
    "Answer published": "Resposta publicada",
    "age symmetric passphrase": "Contrasinal simétrico de age",
    "Server host override": "Host alternativo do Servidor",
    "Use enrolled Server host": "Usar o host do Servidor rexistrado"
  },
  "eu": {
    "Capture whole disks from Clients to Server": "Harrapatu Bezeroen disko osoak Zerbitzarira",
    "Review required": "Berrikusi behar da",
    "Select imported known_hosts": "Hautatu inportatutako known_hosts",
    "Select imported SMB credential": "Hautatu inportatutako SMB kredentziala",
    "Cancel edit": "Utzi edizioa",
    "SSH known_hosts": "SSH known_hosts",
    "SMB credentials": "SMB kredentzialak",
    "Import and encrypt credential": "Inportatu eta enkriptatu kredentziala",
    "Encrypted reference": "Erreferentzia enkriptatua",
    "Action": "Ekintza",
    "No encrypted credentials imported.": "Ez da kredentzial enkriptaturik inportatu.",
    "Check mount identity": "Egiaztatu muntatze-identitatea",
    "Management connectivity protection": "Kudeaketa-konektibitatearen babesa",
    "Apply and verify network configuration": "Aplikatu eta egiaztatu sare-konfigurazioa",
    "Select an interface/address…": "Hautatu interfazea/helbidea…",
    "No eligible IPv4 interface found": "Ez da IPv4 interfaze erabilgarririk aurkitu",
    "Existing DHCP server detected": "Lehendik dagoen DHCP zerbitzaria detektatu da",
    "Server configuration exists": "Zerbitzariaren konfigurazioa badago",
    "Client authentication disabled": "Bezeroen autentifikazioa desgaituta",
    "New Server private key; existing CA retained": "Zerbitzariaren gako pribatu berria; CA zaharra mantentzen da",
    "Submit passphrase to this Live client": "Bidali pasahitza Live Bezero honetara",
    "Passphrase submitted": "Pasahitza bidalita",
    "PXE preflight passed": "PXE aurre-egiaztapena gainditu da",
    "Network topology warning": "Sare-topologiaren abisua",
    "PXE services active": "PXE zerbitzuak aktibo",
    "PXE runtime needs inspection": "PXE exekuzioak ikuskapena behar du",
    "Preflight only": "Aurre-egiaztapena soilik",
    "Client service status": "Bezero-zerbitzuaren egoera",
    "Refresh Client status": "Freskatu Bezeroaren egoera",
    "Server deployment configuration": "Zerbitzariaren inplementazio-konfigurazioa",
    "Client deployment configuration": "Bezeroaren inplementazio-konfigurazioa",
    "Server setup": "Zerbitzariaren konfigurazioa",
    "Server TLS keypair rotated": "Zerbitzariaren TLS gako-parea biratuta",
    "Existing CA and private key will be retained": "Lehendik dauden CA eta gako pribatua mantenduko dira",
    "Server certificate renewed": "Zerbitzariaren ziurtagiria berrituta",
    "DHCP mode": "DHCP modua",
    "Authoritative DHCP can disrupt an existing network": "DHCP autoritatiboak lehendik dagoen sarea eten dezake",
    "DHCP pool start": "DHCP barrutiaren hasiera",
    "DHCP pool end": "DHCP barrutiaren amaiera",
    "Lease duration": "Esleipenaren iraupena",
    "DNS server (optional)": "DNS zerbitzaria (aukerakoa)",
    "HTTP boot asset port": "HTTP abio-aktiboen ataka",
    "Maximum distinct PXE clients": "Bezero desberdinen gehieneko kopurua",
    "Maximum PXE serving time (seconds)": "PXE zerbitzuaren gehieneko denbora (segundoak)",
    "PXE runtime is configured": "PXE ingurunea konfiguratuta dago",
    "Destructive operation guard": "Eragiketa suntsitzaileen babesa",
    "Prewritten answer file (JSON)": "Aurrez idatzitako erantzun-fitxategia (JSON)",
    "Answer published": "Erantzuna argitaratuta",
    "age symmetric passphrase": "age pasahitz simetrikoa",
    "Server host override": "Zerbitzariaren ostalari-ordezkoa",
    "Use enrolled Server host": "Erabili erregistratutako Zerbitzari-ostalaria"
  },
  "pt": {
    "Capture whole disks from Clients to Server": "Capturar discos completos dos Clientes para o Servidor",
    "Review required": "Revisão necessária",
    "Select imported known_hosts": "Selecionar known_hosts importado",
    "Select imported SMB credential": "Selecionar credencial SMB importada",
    "Cancel edit": "Cancelar edição",
    "SSH known_hosts": "known_hosts SSH",
    "SMB credentials": "Credenciais SMB",
    "Import and encrypt credential": "Importar e encriptar credencial",
    "Encrypted reference": "Referência encriptada",
    "Action": "Ação",
    "No encrypted credentials imported.": "Não foram importadas credenciais encriptadas.",
    "Check mount identity": "Verificar identidade da montagem",
    "Management connectivity protection": "Proteção da conectividade de gestão",
    "Apply and verify network configuration": "Aplicar e verificar a configuração de rede",
    "Select an interface/address…": "Selecionar interface/endereço…",
    "No eligible IPv4 interface found": "Não foi encontrada uma interface IPv4 elegível",
    "Existing DHCP server detected": "Foi detetado um servidor DHCP existente",
    "Server configuration exists": "A configuração do Servidor existe",
    "Client authentication disabled": "Autenticação de Clientes desativada",
    "New Server private key; existing CA retained": "Nova chave privada do Servidor; CA existente mantida",
    "Submit passphrase to this Live client": "Enviar frase-passe para este Cliente Live",
    "Passphrase submitted": "Frase-passe enviada",
    "PXE preflight passed": "Pré-verificação PXE aprovada",
    "Network topology warning": "Aviso de topologia de rede",
    "PXE services active": "Serviços PXE ativos",
    "PXE runtime needs inspection": "O ambiente PXE requer inspeção",
    "Preflight only": "Apenas pré-verificação",
    "Client service status": "Estado do serviço do Cliente",
    "Refresh Client status": "Atualizar estado do Cliente",
    "Server deployment configuration": "Configuração de implementação do Servidor",
    "Client deployment configuration": "Configuração de implementação do Cliente",
    "Server setup": "Configuração do Servidor",
    "Server TLS keypair rotated": "Par de chaves TLS do Servidor rodado",
    "Existing CA and private key will be retained": "A CA e a chave privada existentes serão mantidas",
    "Server certificate renewed": "Certificado do Servidor renovado",
    "DHCP mode": "Modo DHCP",
    "Authoritative DHCP can disrupt an existing network": "O DHCP autoritativo pode interromper uma rede existente",
    "DHCP pool start": "Início do intervalo DHCP",
    "DHCP pool end": "Fim do intervalo DHCP",
    "Lease duration": "Duração da concessão",
    "DNS server (optional)": "Servidor DNS (opcional)",
    "HTTP boot asset port": "Porta dos recursos de arranque HTTP",
    "Maximum distinct PXE clients": "Número máximo de Clientes distintos",
    "Maximum PXE serving time (seconds)": "Tempo máximo do serviço PXE (segundos)",
    "PXE runtime is configured": "O ambiente PXE está configurado",
    "Destructive operation guard": "Proteção contra operações destrutivas",
    "Prewritten answer file (JSON)": "Ficheiro de resposta pré-escrito (JSON)",
    "Answer published": "Resposta publicada",
    "age symmetric passphrase": "Frase-passe simétrica age",
    "Server host override": "Anfitrião alternativo do Servidor",
    "Use enrolled Server host": "Usar o anfitrião do Servidor registado"
  },
  "fr": {
    "Capture whole disks from Clients to Server": "Capturer les disques entiers des Clients vers le Serveur",
    "Review required": "Vérification requise",
    "Select imported known_hosts": "Sélectionner le known_hosts importé",
    "Select imported SMB credential": "Sélectionner les identifiants SMB importés",
    "Cancel edit": "Annuler la modification",
    "SSH known_hosts": "known_hosts SSH",
    "SMB credentials": "Identifiants SMB",
    "Import and encrypt credential": "Importer et chiffrer l’identifiant",
    "Encrypted reference": "Référence chiffrée",
    "Action": "Action",
    "No encrypted credentials imported.": "Aucun identifiant chiffré importé.",
    "Check mount identity": "Vérifier l’identité du montage",
    "Management connectivity protection": "Protection de la connectivité d’administration",
    "Apply and verify network configuration": "Appliquer et vérifier la configuration réseau",
    "Select an interface/address…": "Sélectionner l’interface/l’adresse…",
    "No eligible IPv4 interface found": "Aucune interface IPv4 admissible trouvée",
    "Existing DHCP server detected": "Serveur DHCP existant détecté",
    "Server configuration exists": "La configuration du Serveur existe",
    "Client authentication disabled": "Authentification des Clients désactivée",
    "New Server private key; existing CA retained": "Nouvelle clé privée du Serveur ; CA existante conservée",
    "Submit passphrase to this Live client": "Envoyer la phrase secrète à ce Client Live",
    "Passphrase submitted": "Phrase secrète envoyée",
    "PXE preflight passed": "Contrôle préalable PXE réussi",
    "Network topology warning": "Avertissement de topologie réseau",
    "PXE services active": "Services PXE actifs",
    "PXE runtime needs inspection": "L’environnement PXE doit être inspecté",
    "Preflight only": "Contrôle préalable uniquement",
    "Client service status": "État du service Client",
    "Refresh Client status": "Actualiser l’état du Client",
    "Server deployment configuration": "Configuration de déploiement du Serveur",
    "Client deployment configuration": "Configuration de déploiement du Client",
    "Server setup": "Configuration du Serveur",
    "Server TLS keypair rotated": "Paire de clés TLS du Serveur renouvelée",
    "Existing CA and private key will be retained": "La CA et la clé privée existantes seront conservées",
    "Server certificate renewed": "Certificat du Serveur renouvelé",
    "DHCP mode": "Mode DHCP",
    "Authoritative DHCP can disrupt an existing network": "Un DHCP faisant autorité peut perturber un réseau existant",
    "DHCP pool start": "Début de la plage DHCP",
    "DHCP pool end": "Fin de la plage DHCP",
    "Lease duration": "Durée du bail",
    "DNS server (optional)": "Serveur DNS (facultatif)",
    "HTTP boot asset port": "Port des ressources de démarrage HTTP",
    "Maximum distinct PXE clients": "Nombre maximal de Clients distincts",
    "Maximum PXE serving time (seconds)": "Durée maximale du service PXE (secondes)",
    "PXE runtime is configured": "L’environnement PXE est configuré",
    "Destructive operation guard": "Protection contre les opérations destructrices",
    "Prewritten answer file (JSON)": "Fichier de réponse pré-écrit (JSON)",
    "Answer published": "Réponse publiée",
    "age symmetric passphrase": "Phrase secrète symétrique age",
    "Server host override": "Hôte du Serveur de remplacement",
    "Use enrolled Server host": "Utiliser l’hôte du Serveur enregistré"
  },
  "de": {
    "Capture whole disks from Clients to Server": "Vollständige Client-Festplatten auf den Server erfassen",
    "Review required": "Prüfung erforderlich",
    "Select imported known_hosts": "Importierte known_hosts auswählen",
    "Select imported SMB credential": "Importierte SMB-Anmeldedaten auswählen",
    "Cancel edit": "Bearbeitung abbrechen",
    "SSH known_hosts": "SSH-known_hosts",
    "SMB credentials": "SMB-Anmeldedaten",
    "Import and encrypt credential": "Anmeldedaten importieren und verschlüsseln",
    "Encrypted reference": "Verschlüsselte Referenz",
    "Action": "Aktion",
    "No encrypted credentials imported.": "Keine verschlüsselten Anmeldedaten importiert.",
    "Check mount identity": "Mount-Identität prüfen",
    "Management connectivity protection": "Schutz der Verwaltungskonnektivität",
    "Apply and verify network configuration": "Netzwerkkonfiguration anwenden und prüfen",
    "Select an interface/address…": "Schnittstelle/Adresse auswählen…",
    "No eligible IPv4 interface found": "Keine geeignete IPv4-Schnittstelle gefunden",
    "Existing DHCP server detected": "Vorhandener DHCP-Server erkannt",
    "Server configuration exists": "Serverkonfiguration vorhanden",
    "Client authentication disabled": "Client-Authentifizierung deaktiviert",
    "New Server private key; existing CA retained": "Neuer privater Serverschlüssel; vorhandene CA bleibt erhalten",
    "Submit passphrase to this Live client": "Passphrase an diesen Live-Client senden",
    "Passphrase submitted": "Passphrase gesendet",
    "PXE preflight passed": "PXE-Vorprüfung bestanden",
    "Network topology warning": "Warnung zur Netzwerktopologie",
    "PXE services active": "PXE-Dienste aktiv",
    "PXE runtime needs inspection": "PXE-Laufzeit muss geprüft werden",
    "Preflight only": "Nur Vorprüfung",
    "Client service status": "Client-Dienststatus",
    "Refresh Client status": "Client-Status aktualisieren",
    "Server deployment configuration": "Server-Deployment-Konfiguration",
    "Client deployment configuration": "Client-Deployment-Konfiguration",
    "Server setup": "Servereinrichtung",
    "Server TLS keypair rotated": "Server-TLS-Schlüsselpaar rotiert",
    "Existing CA and private key will be retained": "Vorhandene CA und privater Schlüssel bleiben erhalten",
    "Server certificate renewed": "Serverzertifikat erneuert",
    "DHCP mode": "DHCP-Modus",
    "Authoritative DHCP can disrupt an existing network": "Autoritatives DHCP kann ein bestehendes Netzwerk stören",
    "DHCP pool start": "DHCP-Poolstart",
    "DHCP pool end": "DHCP-Poolende",
    "Lease duration": "Lease-Dauer",
    "DNS server (optional)": "DNS-Server (optional)",
    "HTTP boot asset port": "HTTP-Bootasset-Port",
    "Maximum distinct PXE clients": "Maximale Anzahl unterschiedlicher Clients",
    "Maximum PXE serving time (seconds)": "Maximale PXE-Dienstdauer (Sekunden)",
    "PXE runtime is configured": "PXE-Laufzeit ist konfiguriert",
    "Destructive operation guard": "Schutz vor destruktiven Vorgängen",
    "Prewritten answer file (JSON)": "Vorbereitete Antwortdatei (JSON)",
    "Answer published": "Antwort veröffentlicht",
    "age symmetric passphrase": "Symmetrische age-Passphrase",
    "Server host override": "Server-Hostüberschreibung",
    "Use enrolled Server host": "Registrierten Server-Host verwenden"
  },
  "it": {
    "Capture whole disks from Clients to Server": "Acquisisci i dischi interi dei Client sul Server",
    "Review required": "Revisione necessaria",
    "Select imported known_hosts": "Seleziona known_hosts importato",
    "Select imported SMB credential": "Seleziona credenziali SMB importate",
    "Cancel edit": "Annulla modifica",
    "SSH known_hosts": "known_hosts SSH",
    "SMB credentials": "Credenziali SMB",
    "Import and encrypt credential": "Importa e cifra credenziale",
    "Encrypted reference": "Riferimento cifrato",
    "Action": "Azione",
    "No encrypted credentials imported.": "Nessuna credenziale cifrata importata.",
    "Check mount identity": "Verifica identità del mount",
    "Management connectivity protection": "Protezione della connettività di gestione",
    "Apply and verify network configuration": "Applica e verifica la configurazione di rete",
    "Select an interface/address…": "Seleziona interfaccia/indirizzo…",
    "No eligible IPv4 interface found": "Nessuna interfaccia IPv4 idonea trovata",
    "Existing DHCP server detected": "Rilevato un server DHCP esistente",
    "Server configuration exists": "La configurazione del Server esiste",
    "Client authentication disabled": "Autenticazione Client disabilitata",
    "New Server private key; existing CA retained": "Nuova chiave privata del Server; CA esistente mantenuta",
    "Submit passphrase to this Live client": "Invia la passphrase a questo Client Live",
    "Passphrase submitted": "Passphrase inviata",
    "PXE preflight passed": "Controllo preliminare PXE superato",
    "Network topology warning": "Avviso sulla topologia di rete",
    "PXE services active": "Servizi PXE attivi",
    "PXE runtime needs inspection": "Il runtime PXE richiede un controllo",
    "Preflight only": "Solo controllo preliminare",
    "Client service status": "Stato del servizio Client",
    "Refresh Client status": "Aggiorna stato Client",
    "Server deployment configuration": "Configurazione distribuzione Server",
    "Client deployment configuration": "Configurazione distribuzione Client",
    "Server setup": "Configurazione Server",
    "Server TLS keypair rotated": "Coppia di chiavi TLS del Server ruotata",
    "Existing CA and private key will be retained": "La CA e la chiave privata esistenti saranno mantenute",
    "Server certificate renewed": "Certificato del Server rinnovato",
    "DHCP mode": "Modalità DHCP",
    "Authoritative DHCP can disrupt an existing network": "Il DHCP autorevole può interrompere una rete esistente",
    "DHCP pool start": "Inizio intervallo DHCP",
    "DHCP pool end": "Fine intervallo DHCP",
    "Lease duration": "Durata lease",
    "DNS server (optional)": "Server DNS (opzionale)",
    "HTTP boot asset port": "Porta delle risorse di avvio HTTP",
    "Maximum distinct PXE clients": "Numero massimo di Client distinti",
    "Maximum PXE serving time (seconds)": "Durata massima del servizio PXE (secondi)",
    "PXE runtime is configured": "Runtime PXE configurato",
    "Destructive operation guard": "Protezione contro operazioni distruttive",
    "Prewritten answer file (JSON)": "File di risposta precompilato (JSON)",
    "Answer published": "Risposta pubblicata",
    "age symmetric passphrase": "Passphrase simmetrica age",
    "Server host override": "Override host Server",
    "Use enrolled Server host": "Usa l'host Server registrato"
  },
  "zh": {
    "Capture whole disks from Clients to Server": "将客户端整盘采集到服务器",
    "Review required": "需要检查",
    "Select imported known_hosts": "选择已导入的 known_hosts",
    "Select imported SMB credential": "选择已导入的 SMB 凭据",
    "Cancel edit": "取消编辑",
    "SSH known_hosts": "SSH known_hosts",
    "SMB credentials": "SMB 凭据",
    "Import and encrypt credential": "导入并加密凭据",
    "Encrypted reference": "加密引用",
    "Action": "操作",
    "No encrypted credentials imported.": "未导入加密凭据。",
    "Check mount identity": "检查挂载身份",
    "Management connectivity protection": "管理连接保护",
    "Apply and verify network configuration": "应用并验证网络配置",
    "Select an interface/address…": "选择接口/地址…",
    "No eligible IPv4 interface found": "未找到符合条件的 IPv4 接口",
    "Existing DHCP server detected": "检测到现有 DHCP 服务器",
    "Server configuration exists": "服务器配置已存在",
    "Client authentication disabled": "客户端身份验证已禁用",
    "New Server private key; existing CA retained": "新的服务器私钥；保留现有 CA",
    "Submit passphrase to this Live client": "向此 Live 客户端发送口令",
    "Passphrase submitted": "口令已提交",
    "PXE preflight passed": "PXE 预检通过",
    "Network topology warning": "网络拓扑警告",
    "PXE services active": "PXE 服务已启用",
    "PXE runtime needs inspection": "需要检查 PXE 运行状态",
    "Preflight only": "仅预检",
    "Client service status": "客户端服务状态",
    "Refresh Client status": "刷新客户端状态",
    "Server deployment configuration": "服务器部署配置",
    "Client deployment configuration": "客户端部署配置",
    "Server setup": "服务器设置",
    "Server TLS keypair rotated": "服务器 TLS 密钥对已轮换",
    "Existing CA and private key will be retained": "保留现有 CA 和私钥",
    "Server certificate renewed": "服务器证书已续订",
    "DHCP mode": "DHCP 模式",
    "Authoritative DHCP can disrupt an existing network": "权威 DHCP 可能中断现有网络",
    "DHCP pool start": "DHCP 地址池起始地址",
    "DHCP pool end": "DHCP 地址池结束地址",
    "Lease duration": "租约时长",
    "DNS server (optional)": "DNS 服务器（可选）",
    "HTTP boot asset port": "HTTP 启动资源端口",
    "Maximum distinct PXE clients": "不同客户端的最大数量",
    "Maximum PXE serving time (seconds)": "PXE 服务最长时间（秒）",
    "PXE runtime is configured": "PXE 运行环境已配置",
    "Destructive operation guard": "破坏性操作保护",
    "Prewritten answer file (JSON)": "预先编写的应答文件（JSON）",
    "Answer published": "应答已发布",
    "age symmetric passphrase": "age 对称口令",
    "Server host override": "服务器主机覆盖",
    "Use enrolled Server host": "使用已登记的服务器主机"
  },
  "ja": {
    "Capture whole disks from Clients to Server": "Client のディスク全体を Server に取り込む",
    "Review required": "確認が必要",
    "Select imported known_hosts": "インポート済み known_hosts を選択",
    "Select imported SMB credential": "インポート済み SMB 資格情報を選択",
    "Cancel edit": "編集をキャンセル",
    "SSH known_hosts": "SSH known_hosts",
    "SMB credentials": "SMB 資格情報",
    "Import and encrypt credential": "資格情報をインポートして暗号化",
    "Encrypted reference": "暗号化された参照",
    "Action": "操作",
    "No encrypted credentials imported.": "暗号化された資格情報はインポートされていません。",
    "Check mount identity": "マウント ID を確認",
    "Management connectivity protection": "管理接続の保護",
    "Apply and verify network configuration": "ネットワーク設定を適用して検証",
    "Select an interface/address…": "インターフェース/アドレスを選択…",
    "No eligible IPv4 interface found": "使用可能な IPv4 インターフェースがありません",
    "Existing DHCP server detected": "既存の DHCP サーバーを検出しました",
    "Server configuration exists": "Server 設定が存在します",
    "Client authentication disabled": "Client 認証は無効です",
    "New Server private key; existing CA retained": "新しい Server 秘密鍵。既存 CA は保持されます",
    "Submit passphrase to this Live client": "この Live Client にパスフレーズを送信",
    "Passphrase submitted": "パスフレーズを送信しました",
    "PXE preflight passed": "PXE 事前確認に合格しました",
    "Network topology warning": "ネットワーク構成の警告",
    "PXE services active": "PXE サービスは有効です",
    "PXE runtime needs inspection": "PXE ランタイムの確認が必要です",
    "Preflight only": "事前確認のみ",
    "Client service status": "Client サービスの状態",
    "Refresh Client status": "Client の状態を更新",
    "Server deployment configuration": "Server デプロイ設定",
    "Client deployment configuration": "Client デプロイ設定",
    "Server setup": "Server の設定",
    "Server TLS keypair rotated": "Server TLS キーペアをローテーションしました",
    "Existing CA and private key will be retained": "既存の CA と秘密鍵は保持されます",
    "Server certificate renewed": "Server 証明書を更新しました",
    "DHCP mode": "DHCP モード",
    "Authoritative DHCP can disrupt an existing network": "権威 DHCP は既存ネットワークを中断する可能性があります",
    "DHCP pool start": "DHCP プール開始",
    "DHCP pool end": "DHCP プール終了",
    "Lease duration": "リース期間",
    "DNS server (optional)": "DNS サーバー（任意）",
    "HTTP boot asset port": "HTTP ブートアセットポート",
    "Maximum distinct PXE clients": "異なる Client の最大数",
    "Maximum PXE serving time (seconds)": "PXE 提供の最大時間（秒）",
    "PXE runtime is configured": "PXE ランタイムは設定済み",
    "Destructive operation guard": "破壊的操作のガード",
    "Prewritten answer file (JSON)": "事前作成された応答ファイル（JSON）",
    "Answer published": "応答を公開しました",
    "age symmetric passphrase": "age 対称パスフレーズ",
    "Server host override": "Server ホストの上書き",
    "Use enrolled Server host": "登録済み Server ホストを使用"
  },
  "ru": {
    "Capture whole disks from Clients to Server": "Собирать целые диски клиентов на сервер",
    "Review required": "Требуется проверка",
    "Select imported known_hosts": "Выбрать импортированный known_hosts",
    "Select imported SMB credential": "Выбрать импортированные учётные данные SMB",
    "Cancel edit": "Отменить редактирование",
    "SSH known_hosts": "SSH known_hosts",
    "SMB credentials": "Учётные данные SMB",
    "Import and encrypt credential": "Импортировать и зашифровать учётные данные",
    "Encrypted reference": "Зашифрованная ссылка",
    "Action": "Действие",
    "No encrypted credentials imported.": "Зашифрованные учётные данные не импортированы.",
    "Check mount identity": "Проверить идентификатор монтирования",
    "Management connectivity protection": "Защита административного подключения",
    "Apply and verify network configuration": "Применить и проверить сетевую конфигурацию",
    "Select an interface/address…": "Выберите интерфейс/адрес…",
    "No eligible IPv4 interface found": "Подходящий IPv4-интерфейс не найден",
    "Existing DHCP server detected": "Обнаружен существующий DHCP-сервер",
    "Server configuration exists": "Конфигурация сервера существует",
    "Client authentication disabled": "Аутентификация клиентов отключена",
    "New Server private key; existing CA retained": "Новый закрытый ключ сервера; существующий CA сохранён",
    "Submit passphrase to this Live client": "Отправить парольную фразу этому Live-клиенту",
    "Passphrase submitted": "Парольная фраза отправлена",
    "PXE preflight passed": "Предварительная проверка PXE пройдена",
    "Network topology warning": "Предупреждение о топологии сети",
    "PXE services active": "Службы PXE активны",
    "PXE runtime needs inspection": "Среду PXE необходимо проверить",
    "Preflight only": "Только предварительная проверка",
    "Client service status": "Состояние службы клиента",
    "Refresh Client status": "Обновить состояние клиента",
    "Server deployment configuration": "Конфигурация развёртывания сервера",
    "Client deployment configuration": "Конфигурация развёртывания клиента",
    "Server setup": "Настройка сервера",
    "Server TLS keypair rotated": "Пара ключей TLS сервера заменена",
    "Existing CA and private key will be retained": "Существующие CA и закрытый ключ будут сохранены",
    "Server certificate renewed": "Сертификат сервера обновлён",
    "DHCP mode": "Режим DHCP",
    "Authoritative DHCP can disrupt an existing network": "Авторитетный DHCP может нарушить работу существующей сети",
    "DHCP pool start": "Начало пула DHCP",
    "DHCP pool end": "Конец пула DHCP",
    "Lease duration": "Срок аренды",
    "DNS server (optional)": "DNS-сервер (необязательно)",
    "HTTP boot asset port": "Порт HTTP-ресурсов загрузки",
    "Maximum distinct PXE clients": "Максимум уникальных клиентов",
    "Maximum PXE serving time (seconds)": "Максимальное время работы PXE (секунды)",
    "PXE runtime is configured": "Среда PXE настроена",
    "Destructive operation guard": "Защита от разрушительных операций",
    "Prewritten answer file (JSON)": "Заранее подготовленный файл ответа (JSON)",
    "Answer published": "Ответ опубликован",
    "age symmetric passphrase": "Симметричная парольная фраза age",
    "Server host override": "Переопределение узла сервера",
    "Use enrolled Server host": "Использовать зарегистрированный узел сервера"
  },
  "ar": {
    "Capture whole disks from Clients to Server": "التقاط الأقراص الكاملة من العملاء إلى الخادم",
    "Review required": "المراجعة مطلوبة",
    "Select imported known_hosts": "اختر known_hosts المستورد",
    "Select imported SMB credential": "اختر بيانات اعتماد SMB المستوردة",
    "Cancel edit": "إلغاء التحرير",
    "SSH known_hosts": "known_hosts لـ SSH",
    "SMB credentials": "بيانات اعتماد SMB",
    "Import and encrypt credential": "استيراد بيانات الاعتماد وتشفيرها",
    "Encrypted reference": "مرجع مشفر",
    "Action": "الإجراء",
    "No encrypted credentials imported.": "لم يتم استيراد بيانات اعتماد مشفرة.",
    "Check mount identity": "التحقق من هوية التحميل",
    "Management connectivity protection": "حماية اتصال الإدارة",
    "Apply and verify network configuration": "تطبيق إعداد الشبكة والتحقق منه",
    "Select an interface/address…": "اختر الواجهة/العنوان…",
    "No eligible IPv4 interface found": "لم يتم العثور على واجهة IPv4 مؤهلة",
    "Existing DHCP server detected": "تم اكتشاف خادم DHCP موجود",
    "Server configuration exists": "إعداد الخادم موجود",
    "Client authentication disabled": "مصادقة العملاء معطلة",
    "New Server private key; existing CA retained": "مفتاح خاص جديد للخادم؛ تم الاحتفاظ بسلطة الشهادات الحالية",
    "Submit passphrase to this Live client": "إرسال عبارة المرور إلى عميل Live هذا",
    "Passphrase submitted": "تم إرسال عبارة المرور",
    "PXE preflight passed": "اجتاز فحص PXE المسبق",
    "Network topology warning": "تحذير بشأن بنية الشبكة",
    "PXE services active": "خدمات PXE نشطة",
    "PXE runtime needs inspection": "يلزم فحص بيئة PXE",
    "Preflight only": "فحص مسبق فقط",
    "Client service status": "حالة خدمة العميل",
    "Refresh Client status": "تحديث حالة العميل",
    "Server deployment configuration": "إعداد نشر الخادم",
    "Client deployment configuration": "إعداد نشر العميل",
    "Server setup": "إعداد الخادم",
    "Server TLS keypair rotated": "تم تدوير زوج مفاتيح TLS للخادم",
    "Existing CA and private key will be retained": "سيتم الاحتفاظ بسلطة الشهادات والمفتاح الخاص الحاليين",
    "Server certificate renewed": "تم تجديد شهادة الخادم",
    "DHCP mode": "وضع DHCP",
    "Authoritative DHCP can disrupt an existing network": "قد يؤدي DHCP الموثوق إلى تعطيل شبكة موجودة",
    "DHCP pool start": "بداية نطاق DHCP",
    "DHCP pool end": "نهاية نطاق DHCP",
    "Lease duration": "مدة الإيجار",
    "DNS server (optional)": "خادم DNS (اختياري)",
    "HTTP boot asset port": "منفذ أصول إقلاع HTTP",
    "Maximum distinct PXE clients": "الحد الأقصى للعملاء المميزين",
    "Maximum PXE serving time (seconds)": "الحد الأقصى لمدة خدمة PXE (بالثواني)",
    "PXE runtime is configured": "بيئة PXE مُعدة",
    "Destructive operation guard": "حماية العمليات المدمرة",
    "Prewritten answer file (JSON)": "ملف إجابة مكتوب مسبقاً (JSON)",
    "Answer published": "تم نشر الإجابة",
    "age symmetric passphrase": "عبارة مرور age متماثلة",
    "Server host override": "تجاوز مضيف الخادم",
    "Use enrolled Server host": "استخدام مضيف الخادم المسجل"
  },
  "tr": {
    "Capture whole disks from Clients to Server": "İstemcilerin tüm disklerini Sunucuya yakala",
    "Review required": "İnceleme gerekli",
    "Select imported known_hosts": "İçe aktarılan known_hosts dosyasını seç",
    "Select imported SMB credential": "İçe aktarılan SMB kimlik bilgilerini seç",
    "Cancel edit": "Düzenlemeyi iptal et",
    "SSH known_hosts": "SSH known_hosts",
    "SMB credentials": "SMB kimlik bilgileri",
    "Import and encrypt credential": "Kimlik bilgisini içe aktar ve şifrele",
    "Encrypted reference": "Şifrelenmiş başvuru",
    "Action": "Eylem",
    "No encrypted credentials imported.": "Şifrelenmiş kimlik bilgisi içe aktarılmadı.",
    "Check mount identity": "Bağlama kimliğini denetle",
    "Management connectivity protection": "Yönetim bağlantısı koruması",
    "Apply and verify network configuration": "Ağ yapılandırmasını uygula ve doğrula",
    "Select an interface/address…": "Arayüz/adres seç…",
    "No eligible IPv4 interface found": "Uygun IPv4 arayüzü bulunamadı",
    "Existing DHCP server detected": "Mevcut DHCP sunucusu algılandı",
    "Server configuration exists": "Sunucu yapılandırması mevcut",
    "Client authentication disabled": "İstemci kimlik doğrulaması devre dışı",
    "New Server private key; existing CA retained": "Yeni Sunucu özel anahtarı; mevcut CA korunur",
    "Submit passphrase to this Live client": "Parolayı bu Live İstemciye gönder",
    "Passphrase submitted": "Parola gönderildi",
    "PXE preflight passed": "PXE ön denetimi başarılı",
    "Network topology warning": "Ağ topolojisi uyarısı",
    "PXE services active": "PXE hizmetleri etkin",
    "PXE runtime needs inspection": "PXE çalışma zamanı incelenmeli",
    "Preflight only": "Yalnızca ön denetim",
    "Client service status": "İstemci hizmet durumu",
    "Refresh Client status": "İstemci durumunu yenile",
    "Server deployment configuration": "Sunucu dağıtım yapılandırması",
    "Client deployment configuration": "İstemci dağıtım yapılandırması",
    "Server setup": "Sunucu kurulumu",
    "Server TLS keypair rotated": "Sunucu TLS anahtar çifti döndürüldü",
    "Existing CA and private key will be retained": "Mevcut CA ve özel anahtar korunacak",
    "Server certificate renewed": "Sunucu sertifikası yenilendi",
    "DHCP mode": "DHCP modu",
    "Authoritative DHCP can disrupt an existing network": "Yetkili DHCP mevcut bir ağı kesintiye uğratabilir",
    "DHCP pool start": "DHCP havuzu başlangıcı",
    "DHCP pool end": "DHCP havuzu sonu",
    "Lease duration": "Kiralama süresi",
    "DNS server (optional)": "DNS sunucusu (isteğe bağlı)",
    "HTTP boot asset port": "HTTP önyükleme varlık bağlantı noktası",
    "Maximum distinct PXE clients": "En fazla farklı İstemci sayısı",
    "Maximum PXE serving time (seconds)": "En uzun PXE hizmet süresi (saniye)",
    "PXE runtime is configured": "PXE çalışma zamanı yapılandırıldı",
    "Destructive operation guard": "Yıkıcı işlem koruması",
    "Prewritten answer file (JSON)": "Önceden yazılmış yanıt dosyası (JSON)",
    "Answer published": "Yanıt yayımlandı",
    "age symmetric passphrase": "age simetrik parola",
    "Server host override": "Sunucu ana bilgisayar geçersiz kılması",
    "Use enrolled Server host": "Kayıtlı Sunucu ana bilgisayarını kullan"
  }
};
for (const [language, values] of Object.entries(APP_UI_TEXT_MISC)) Object.assign(DICTS[language], values);
const APP_UI_TEXT_LAYOUT = {
  "es": {
    "NetworkManager connection profile": "Perfil de conexión de NetworkManager",
    "IPv4 configuration": "Configuración IPv4",
    "Prefix length": "Longitud del prefijo",
    "Gateway (optional)": "Puerta de enlace (opcional)",
    "DNS servers (comma-separated, optional)": "Servidores DNS (separados por comas, opcional)",
    "Network configuration verified": "Configuración de red verificada",
    "This is the identity bootstrap step only": "Este es solo el paso de inicialización de identidad",
    "Server network interface and address": "Interfaz de red y dirección del Servidor",
    "Restore source partition layout preview": "Vista previa de la distribución de particiones de restauración",
    "Whole-disk source image": "Imagen de disco completo de origen",
    "Verified partition-table preview": "Vista previa verificada de la tabla de particiones",
    "Source image partition layout": "Distribución de particiones de la imagen de origen",
    "Partition to extract": "Partición que se extraerá",
    "Partition extraction progress": "Progreso de extracción de partición",
    "Partition image published": "Imagen de partición publicada",
    "Verification failed": "La verificación ha fallado"
  },
  "ca": {
    "NetworkManager connection profile": "Perfil de connexió de NetworkManager",
    "IPv4 configuration": "Configuració IPv4",
    "Prefix length": "Longitud del prefix",
    "Gateway (optional)": "Passarel·la (opcional)",
    "DNS servers (comma-separated, optional)": "Servidors DNS (separats per comes, opcional)",
    "Network configuration verified": "Configuració de xarxa verificada",
    "This is the identity bootstrap step only": "Aquest és només el pas d'inicialització de la identitat",
    "Server network interface and address": "Interfície de xarxa i adreça del Servidor",
    "Restore source partition layout preview": "Previsualització de la distribució de particions de restauració",
    "Whole-disk source image": "Imatge de disc sencer d'origen",
    "Verified partition-table preview": "Previsualització verificada de la taula de particions",
    "Source image partition layout": "Distribució de particions de la imatge d'origen",
    "Partition to extract": "Partició que s'extraurà",
    "Partition extraction progress": "Progrés d'extracció de la partició",
    "Partition image published": "Imatge de partició publicada",
    "Verification failed": "La verificació ha fallat"
  },
  "gl": {
    "NetworkManager connection profile": "Perfil de conexión de NetworkManager",
    "IPv4 configuration": "Configuración IPv4",
    "Prefix length": "Lonxitude do prefixo",
    "Gateway (optional)": "Pasarela (opcional)",
    "DNS servers (comma-separated, optional)": "Servidores DNS (separados por comas, opcional)",
    "Network configuration verified": "Configuración de rede verificada",
    "This is the identity bootstrap step only": "Este é só o paso de inicialización da identidade",
    "Server network interface and address": "Interface de rede e enderezo do Servidor",
    "Restore source partition layout preview": "Vista previa da distribución de particións de restauración",
    "Whole-disk source image": "Imaxe de disco completo de orixe",
    "Verified partition-table preview": "Vista previa verificada da táboa de particións",
    "Source image partition layout": "Distribución de particións da imaxe de orixe",
    "Partition to extract": "Partición que se extraerá",
    "Partition extraction progress": "Progreso da extracción da partición",
    "Partition image published": "Imaxe de partición publicada",
    "Verification failed": "Fallou a verificación"
  },
  "eu": {
    "NetworkManager connection profile": "NetworkManager konexio-profila",
    "IPv4 configuration": "IPv4 konfigurazioa",
    "Prefix length": "Aurrizkiaren luzera",
    "Gateway (optional)": "Atebidea (aukerakoa)",
    "DNS servers (comma-separated, optional)": "DNS zerbitzariak (komaz bereizita, aukerakoa)",
    "Network configuration verified": "Sare-konfigurazioa egiaztatuta",
    "This is the identity bootstrap step only": "Hau identitatea hasieratzeko urratsa baino ez da",
    "Server network interface and address": "Zerbitzariaren sare-interfazea eta helbidea",
    "Restore source partition layout preview": "Berrezarpeneko partizio-diseinuaren aurrebista",
    "Whole-disk source image": "Jatorrizko disko osoko irudia",
    "Verified partition-table preview": "Partizio-taularen aurrebista egiaztatua",
    "Source image partition layout": "Jatorrizko irudiaren partizio-diseinua",
    "Partition to extract": "Atera beharreko partizioa",
    "Partition extraction progress": "Partizioa ateratzeko aurrerapena",
    "Partition image published": "Partizio-irudia argitaratuta",
    "Verification failed": "Egiaztapenak huts egin du"
  },
  "pt": {
    "NetworkManager connection profile": "Perfil de ligação do NetworkManager",
    "IPv4 configuration": "Configuração IPv4",
    "Prefix length": "Comprimento do prefixo",
    "Gateway (optional)": "Gateway (opcional)",
    "DNS servers (comma-separated, optional)": "Servidores DNS (separados por vírgulas, opcional)",
    "Network configuration verified": "Configuração de rede verificada",
    "This is the identity bootstrap step only": "Este é apenas o passo de inicialização da identidade",
    "Server network interface and address": "Interface de rede e endereço do Servidor",
    "Restore source partition layout preview": "Pré-visualização da disposição das partições do restauro",
    "Whole-disk source image": "Imagem de disco completo de origem",
    "Verified partition-table preview": "Pré-visualização verificada da tabela de partições",
    "Source image partition layout": "Disposição das partições da imagem de origem",
    "Partition to extract": "Partição a extrair",
    "Partition extraction progress": "Progresso da extração da partição",
    "Partition image published": "Imagem da partição publicada",
    "Verification failed": "A verificação falhou"
  },
  "fr": {
    "NetworkManager connection profile": "Profil de connexion NetworkManager",
    "IPv4 configuration": "Configuration IPv4",
    "Prefix length": "Longueur du préfixe",
    "Gateway (optional)": "Passerelle (facultatif)",
    "DNS servers (comma-separated, optional)": "Serveurs DNS (séparés par des virgules, facultatif)",
    "Network configuration verified": "Configuration réseau vérifiée",
    "This is the identity bootstrap step only": "Cette étape initialise uniquement l’identité",
    "Server network interface and address": "Interface réseau et adresse du Serveur",
    "Restore source partition layout preview": "Aperçu de la disposition des partitions à restaurer",
    "Whole-disk source image": "Image source du disque entier",
    "Verified partition-table preview": "Aperçu vérifié de la table de partitions",
    "Source image partition layout": "Disposition des partitions de l’image source",
    "Partition to extract": "Partition à extraire",
    "Partition extraction progress": "Progression de l’extraction de partition",
    "Partition image published": "Image de partition publiée",
    "Verification failed": "Échec de la vérification"
  },
  "de": {
    "NetworkManager connection profile": "NetworkManager-Verbindungsprofil",
    "IPv4 configuration": "IPv4-Konfiguration",
    "Prefix length": "Präfixlänge",
    "Gateway (optional)": "Gateway (optional)",
    "DNS servers (comma-separated, optional)": "DNS-Server (durch Kommas getrennt, optional)",
    "Network configuration verified": "Netzwerkkonfiguration verifiziert",
    "This is the identity bootstrap step only": "Dieser Schritt initialisiert nur die Identität",
    "Server network interface and address": "Netzwerkschnittstelle und Adresse des Servers",
    "Restore source partition layout preview": "Vorschau des Partitionslayouts für die Wiederherstellung",
    "Whole-disk source image": "Quell-Image der gesamten Festplatte",
    "Verified partition-table preview": "Verifizierte Vorschau der Partitionstabelle",
    "Source image partition layout": "Partitionslayout des Quell-Images",
    "Partition to extract": "Zu extrahierende Partition",
    "Partition extraction progress": "Fortschritt der Partitionsextraktion",
    "Partition image published": "Partitions-Image veröffentlicht",
    "Verification failed": "Überprüfung fehlgeschlagen"
  },
  "it": {
    "NetworkManager connection profile": "Profilo di connessione NetworkManager",
    "IPv4 configuration": "Configurazione IPv4",
    "Prefix length": "Lunghezza del prefisso",
    "Gateway (optional)": "Gateway (opzionale)",
    "DNS servers (comma-separated, optional)": "Server DNS (separati da virgole, opzionale)",
    "Network configuration verified": "Configurazione di rete verificata",
    "This is the identity bootstrap step only": "Questo è solo il passaggio di inizializzazione dell'identità",
    "Server network interface and address": "Interfaccia di rete e indirizzo del Server",
    "Restore source partition layout preview": "Anteprima del layout delle partizioni da ripristinare",
    "Whole-disk source image": "Immagine sorgente dell'intero disco",
    "Verified partition-table preview": "Anteprima verificata della tabella delle partizioni",
    "Source image partition layout": "Layout delle partizioni dell'immagine sorgente",
    "Partition to extract": "Partizione da estrarre",
    "Partition extraction progress": "Avanzamento estrazione partizione",
    "Partition image published": "Immagine della partizione pubblicata",
    "Verification failed": "Verifica non riuscita"
  },
  "zh": {
    "NetworkManager connection profile": "NetworkManager 连接配置文件",
    "IPv4 configuration": "IPv4 配置",
    "Prefix length": "前缀长度",
    "Gateway (optional)": "网关（可选）",
    "DNS servers (comma-separated, optional)": "DNS 服务器（逗号分隔，可选）",
    "Network configuration verified": "网络配置已验证",
    "This is the identity bootstrap step only": "此步骤仅用于初始化身份",
    "Server network interface and address": "服务器网络接口和地址",
    "Restore source partition layout preview": "恢复分区布局预览",
    "Whole-disk source image": "源整盘映像",
    "Verified partition-table preview": "已验证的分区表预览",
    "Source image partition layout": "源映像分区布局",
    "Partition to extract": "要提取的分区",
    "Partition extraction progress": "分区提取进度",
    "Partition image published": "分区映像已发布",
    "Verification failed": "验证失败"
  },
  "ja": {
    "NetworkManager connection profile": "NetworkManager 接続プロファイル",
    "IPv4 configuration": "IPv4 設定",
    "Prefix length": "プレフィックス長",
    "Gateway (optional)": "ゲートウェイ（任意）",
    "DNS servers (comma-separated, optional)": "DNS サーバー（カンマ区切り、任意）",
    "Network configuration verified": "ネットワーク設定を検証しました",
    "This is the identity bootstrap step only": "この手順は ID の初期化のみを行います",
    "Server network interface and address": "Server のネットワークインターフェースとアドレス",
    "Restore source partition layout preview": "復元するパーティションレイアウトのプレビュー",
    "Whole-disk source image": "ソースディスク全体のイメージ",
    "Verified partition-table preview": "検証済みパーティションテーブルのプレビュー",
    "Source image partition layout": "ソースイメージのパーティションレイアウト",
    "Partition to extract": "抽出するパーティション",
    "Partition extraction progress": "パーティション抽出の進行状況",
    "Partition image published": "パーティションイメージを公開しました",
    "Verification failed": "検証に失敗しました"
  },
  "ru": {
    "NetworkManager connection profile": "Профиль подключения NetworkManager",
    "IPv4 configuration": "Конфигурация IPv4",
    "Prefix length": "Длина префикса",
    "Gateway (optional)": "Шлюз (необязательно)",
    "DNS servers (comma-separated, optional)": "DNS-серверы (через запятую, необязательно)",
    "Network configuration verified": "Сетевая конфигурация проверена",
    "This is the identity bootstrap step only": "Этот шаг выполняет только инициализацию идентификатора",
    "Server network interface and address": "Сетевой интерфейс и адрес сервера",
    "Restore source partition layout preview": "Предварительный просмотр разметки разделов для восстановления",
    "Whole-disk source image": "Исходный образ всего диска",
    "Verified partition-table preview": "Проверенный предварительный просмотр таблицы разделов",
    "Source image partition layout": "Разметка разделов исходного образа",
    "Partition to extract": "Раздел для извлечения",
    "Partition extraction progress": "Ход извлечения раздела",
    "Partition image published": "Образ раздела опубликован",
    "Verification failed": "Проверка не пройдена"
  },
  "ar": {
    "NetworkManager connection profile": "ملف اتصال NetworkManager",
    "IPv4 configuration": "إعداد IPv4",
    "Prefix length": "طول البادئة",
    "Gateway (optional)": "البوابة (اختياري)",
    "DNS servers (comma-separated, optional)": "خوادم DNS (مفصولة بفواصل، اختياري)",
    "Network configuration verified": "تم التحقق من إعداد الشبكة",
    "This is the identity bootstrap step only": "هذه الخطوة لتهيئة الهوية فقط",
    "Server network interface and address": "واجهة شبكة الخادم وعنوانه",
    "Restore source partition layout preview": "معاينة تخطيط الأقسام للاستعادة",
    "Whole-disk source image": "صورة القرص الكامل المصدر",
    "Verified partition-table preview": "معاينة موثقة لجدول الأقسام",
    "Source image partition layout": "تخطيط أقسام الصورة المصدر",
    "Partition to extract": "القسم المراد استخراجه",
    "Partition extraction progress": "تقدم استخراج القسم",
    "Partition image published": "تم نشر صورة القسم",
    "Verification failed": "فشل التحقق"
  },
  "tr": {
    "NetworkManager connection profile": "NetworkManager bağlantı profili",
    "IPv4 configuration": "IPv4 yapılandırması",
    "Prefix length": "Önek uzunluğu",
    "Gateway (optional)": "Ağ geçidi (isteğe bağlı)",
    "DNS servers (comma-separated, optional)": "DNS sunucuları (virgülle ayrılmış, isteğe bağlı)",
    "Network configuration verified": "Ağ yapılandırması doğrulandı",
    "This is the identity bootstrap step only": "Bu yalnızca kimlik başlatma adımıdır",
    "Server network interface and address": "Sunucu ağ arayüzü ve adresi",
    "Restore source partition layout preview": "Geri yükleme bölüm düzeni önizlemesi",
    "Whole-disk source image": "Kaynak tüm disk görüntüsü",
    "Verified partition-table preview": "Doğrulanmış bölüm tablosu önizlemesi",
    "Source image partition layout": "Kaynak görüntünün bölüm düzeni",
    "Partition to extract": "Çıkarılacak bölüm",
    "Partition extraction progress": "Bölüm çıkarma ilerlemesi",
    "Partition image published": "Bölüm görüntüsü yayımlandı",
    "Verification failed": "Doğrulama başarısız"
  }
};
for (const [language, values] of Object.entries(APP_UI_TEXT_LAYOUT)) Object.assign(DICTS[language], values);
for (const [language, values] of Object.entries(CORE_TRANSLATION_COMPLETION)) {
  Object.assign(DICTS[language], values);
}

export function translate(language, key) {
  return EXTRA_TRANSLATIONS[language]?.[key] || DICTS[language]?.[key] || EXTRA_TRANSLATIONS.en[key] || EN[key] || key;
}

export function useLanguagePreference() {
  const [language, setLanguageState] = useState(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const firstBootLanguage = params.get("feclora_language");
      if (LANGUAGES.some(([id]) => id === firstBootLanguage)) {
        window.localStorage.setItem("feclora.ui-language", firstBootLanguage);
        params.delete("feclora_language");
        const query = params.toString();
        window.history.replaceState({}, "", window.location.pathname + (query ? "?" + query : "") + window.location.hash);
        return firstBootLanguage;
      }
      const saved = window.localStorage.getItem("feclora.ui-language");
      if (LANGUAGES.some(([id]) => id === saved)) return saved;
      const browser = (window.navigator.language || "en").slice(0, 2).toLowerCase();
      return LANGUAGES.some(([id]) => id === browser) ? browser : "en";
    } catch { return "en"; }
  });
  const setLanguage = (next) => {
    if (!LANGUAGES.some(([id]) => id === next)) return;
    setLanguageState(next);
    try { window.localStorage.setItem("feclora.ui-language", next); } catch { /* preference remains active for this session */ }
  };
  useEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.dir = language === "ar" ? "rtl" : "ltr";
    try { window.localStorage.setItem("feclora.ui-language", language); } catch { /* browser storage may be disabled */ }
  }, [language]);
  return { language, setLanguage, t: (key) => translate(language, key) };
}
