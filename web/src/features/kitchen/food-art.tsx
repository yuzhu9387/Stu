import Image from "next/image";

const foods = [
  { match: /鸡肉丸|chicken meatball/i, file: "chicken-meatballs", emoji: "🧆" },
  { match: /番茄.*面|tomato.*noodle/i, file: "tomato-beef-noodles", emoji: "🍜" },
  { match: /糙米|brown rice/i, file: "brown-rice", emoji: "🍚" },
  { match: /鱼|fish|salmon/i, file: "steamed-fish", emoji: "🐟" },
  { match: /南瓜粥|pumpkin.*porridge/i, file: "pumpkin-porridge", emoji: "🥣" },
  { match: /虾|shrimp|prawn/i, file: "garlic-shrimp", emoji: "🦐" },
  { match: /面包|bread|toast|吐司/i, file: "wheat-bread", emoji: "🍞" },
  { match: /炒.*面|stir.*noodle/i, file: "stir-fry-noodles", emoji: "🍜" },
];
export function foodEmoji(name: string, type = "Other") {
  return foods.find(food => food.match.test(name))?.emoji ?? (/西兰花|broccoli/.test(name)?"🥦":/胡萝卜|carrot/.test(name)?"🥕":/香蕉|banana|燕麦|oat/.test(name)?"🍌":/蛋|egg/.test(name)?"🥚":/奶|milk/.test(name)?"🥛":/肉|meat|chicken|beef/.test(name)?"🥩":({Protein:"🥩",Carbs:"🍚",Vegetables:"🥦",Baking:"🍞"}[type]??"🥣"));
}
export function RecipeArt({name,type,sizes="(max-width: 760px) 100vw, 520px"}:{name:string;type:string;sizes?:string}) {
  const food=foods.find(food=>food.match.test(name));
  return <div className="kw-recipe-art">{food?<Image src={`/assets/figma/${food.file}.jpg`} width={792} height={336} sizes={sizes} alt={`${name} illustration`}/>:<span aria-hidden="true">{foodEmoji(name,type)}</span>}</div>;
}
