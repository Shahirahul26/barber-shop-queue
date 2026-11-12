// Firebase Phone Auth Configuration (10,000 Free SMS / month)
// Get these values from: Firebase Console -> Project Settings -> General -> Your apps -> Web app
window.firebaseConfig = {
  apiKey: "AIzaSyBDiWZIBupDF9OTqyAd1vjoxmhOrbOc9-c",
  authDomain: "trimtime-web.firebaseapp.com",
  projectId: "trimtime-web",
  storageBucket: "trimtime-web.firebasestorage.app",
  messagingSenderId: "1044327958918",
  appId: "1:1044327958918:web:2dd94374d2a3937706c407",
  measurementId: "G-4RNETZK2QN"
};

(function initFirebase() {
  if (typeof firebase !== "undefined" && window.firebaseConfig && window.firebaseConfig.apiKey) {
    try {
      if (!firebase.apps.length) {
        firebase.initializeApp(window.firebaseConfig);
      }
    } catch (err) {
      console.warn("Firebase initialization:", err);
    }
  }
})();

